// Current v0.10.0 projectile numerics. Each call consumes fresh numeric vectors
// and never retains Python objects, engine references or flight state.
// Exact expression order matters for range termination and hit timestamps.
namespace projectile_math_law {
using Point = std::array<double, 3>;

Point point_values(PyObject *value) {
    require_sequence(value, 3, true);
    Point result = {};
    for (int i = 0; i != 3; ++i)
        result[i] = finite_number(items(value)[i]);
    return result;
}

Point trajectory(const Point &start, const Point &velocity,
                 const Point &gravity, double elapsed) {
    // Python max(0.0, float(elapsed or 0.0)) and its left-to-right operations.
    const double time = elapsed <= 0. ? 0. : elapsed;
    const double half_time_sq = .5 * time * time;
    Point result = {};
    for (int i = 0; i != 3; ++i)
        result[i] = start[i] + velocity[i] * time + gravity[i] * half_time_sq;
    return result;
}

Point lerp(const Point &start, const Point &end, double fraction) {
    // The release clamps before interpolating, including a zero fraction.
    const double amount = std::max(0., std::min(1., fraction));
    Point result = {};
    for (int i = 0; i != 3; ++i)
        result[i] = start[i] + (end[i] - start[i]) * amount;
    return result;
}

struct Chord {
    Point start, end;
    double absolute_end;
    bool distance_terminal;
};

Chord step(const Point &origin, const Point &velocity, const Point &gravity,
           const double *values) {
    // values: launch_time, absolute_start, absolute_end, max_distance,
    //        distance already travelled. No time or distance is quantized.
    const double launch = values[0], absolute_start = values[1];
    const double absolute_end = values[2];
    const Point start = trajectory(origin, velocity, gravity,
                                   absolute_start - launch);
    const Point unconstrained_end = trajectory(origin, velocity, gravity,
                                               absolute_end - launch);
    const double dx = unconstrained_end[0] - start[0];
    const double dy = unconstrained_end[1] - start[1];
    const double dz = unconstrained_end[2] - start[2];
    const double chord_distance = std::sqrt(dx * dx + dy * dy + dz * dz);
    const double remaining = std::max(0., values[3] - values[4]);
    double distance_fraction = 1.;
    bool distance_terminal = false;
    if (chord_distance > remaining) {
        distance_fraction = remaining / chord_distance;
        distance_terminal = true;
    } else if (remaining <= 0.) {
        distance_fraction = 0.;
        distance_terminal = true;
    }
    const Point end = lerp(start, unconstrained_end, distance_fraction);
    const double constrained_time = absolute_start +
        (absolute_end - absolute_start) * distance_fraction;
    return {start, end, constrained_time, distance_terminal};
}

struct MovingChord { Point first, last; };
MovingChord moving_chord(const Point &first, const Point &last,
                         const Point &previous, const Point &current,
                         const double *fractions) {
    const Point at_start = lerp(previous, current, fractions[0]);
    const Point at_end = lerp(previous, current, fractions[1]);
    Point new_start = {}, new_end = {};
    for (int i = 0; i != 3; ++i) {
        new_start[i] = first[i] + current[i] - at_start[i];
        new_end[i] = last[i] + current[i] - at_end[i];
    }
    return {new_start, new_end};
}

bool finite(const Point &values) {
    return std::isfinite(values[0]) && std::isfinite(values[1]) &&
           std::isfinite(values[2]);
}

PyObject *point_result(const Point &values) {
    PyObject *out = tuple_new(3);
    if (!out) return 0;
    for (int i = 0; i != 3; ++i) {
        items(out)[i] = float_new(values[i]);
        if (!items(out)[i]) { decref(out); return 0; }
    }
    return out;
}

PyObject *chord_result(const Chord &chord) {
    PyObject *out = tuple_new(4);
    if (!out) return 0;
    items(out)[0] = point_result(chord.start);
    if (!items(out)[0]) { decref(out); return 0; }
    items(out)[1] = point_result(chord.end);
    if (!items(out)[1]) { decref(out); return 0; }
    items(out)[2] = float_new(chord.absolute_end);
    if (!items(out)[2]) { decref(out); return 0; }
    items(out)[3] = int_new(chord.distance_terminal ? 1L : 0L);
    if (!items(out)[3]) { decref(out); return 0; }
    return out;
}

PyObject *moving_result(const MovingChord &chord) {
    PyObject *out = tuple_new(2);
    if (!out) return 0;
    items(out)[0] = point_result(chord.first);
    if (!items(out)[0]) { decref(out); return 0; }
    items(out)[1] = point_result(chord.last);
    if (!items(out)[1]) { decref(out); return 0; }
    return out;
}
}  // namespace projectile_math_law

#include "offline_internal_mesh_cone_python.inc"

PyObject *WOT_CDECL projectile_math(PyObject *, PyObject *args) {
    NATIVE_PROFILE_ENTRY(projectile_math);
    try {
        require_sequence(args, 3, true);
        PyObject **values = items(args);
        const int op = index_value(values[0]);
        if (op == 2)
            return internal_mesh_cone_law::run(values[1], values[2], profile);
        if (op == 0) {
            require_sequence(values[1], 3, true);
            require_sequence(values[2], 5, true);
            PyObject **vectors = items(values[1]);
            const auto origin = projectile_math_law::point_values(vectors[0]);
            const auto velocity = projectile_math_law::point_values(vectors[1]);
            const auto gravity = projectile_math_law::point_values(vectors[2]);
            double scalars[5];
            for (int i = 0; i != 5; ++i)
                scalars[i] = finite_number(items(values[2])[i]);
            const auto result = profile.run([&] {
                return projectile_math_law::step(origin, velocity, gravity, scalars);
            });
            if (!projectile_math_law::finite(result.start) ||
                !projectile_math_law::finite(result.end) ||
                !std::isfinite(result.absolute_end)) throw Unsupported();
            return projectile_math_law::chord_result(result);
        }
        if (op == 1) {
            require_sequence(values[1], 4, true);
            require_sequence(values[2], 2, true);
            PyObject **vectors = items(values[1]);
            const auto first = projectile_math_law::point_values(vectors[0]);
            const auto last = projectile_math_law::point_values(vectors[1]);
            const auto previous = projectile_math_law::point_values(vectors[2]);
            const auto current = projectile_math_law::point_values(vectors[3]);
            double scalars[2];
            for (int i = 0; i != 2; ++i)
                scalars[i] = finite_number(items(values[2])[i]);
            const auto result = profile.run([&] {
                return projectile_math_law::moving_chord(
                    first, last, previous, current, scalars);
            });
            if (!projectile_math_law::finite(result.first) ||
                !projectile_math_law::finite(result.last)) throw Unsupported();
            return projectile_math_law::moving_result(result);
        }
        throw Unsupported();
    } catch (const PythonAllocationFailed &) {
        profile.fail(); return 0;
    } catch (...) {
        profile.fail(); return fallback();
    }
}
