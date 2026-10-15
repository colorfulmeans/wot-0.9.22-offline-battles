// Current 0.10.0 projectile spatial tests and ricochet response.
// Borrow only exact primitive numeric sequences. No BigWorld objects,
// collision callbacks, saved Python references or cross-frame state.
namespace projectile_spatial_law {
using Vec3 = std::array<double, 3>;

Vec3 vector(PyObject *object) {
    require_sequence(object, 3, true);
    PyObject **values = items(object);
    return {{finite_number(values[0]), finite_number(values[1]),
             finite_number(values[2])}};
}

double segment_distance_sq(const Vec3 &point, const Vec3 &start,
                           const Vec3 &end) {
    const double sx = end[0] - start[0];
    const double sy = end[1] - start[1];
    const double sz = end[2] - start[2];
    const double px = point[0] - start[0];
    const double py = point[1] - start[1];
    const double pz = point[2] - start[2];
    const double denominator = sx * sx + sy * sy + sz * sz;
    if (denominator <= 1.e-12)
        return px * px + py * py + pz * pz;
    double fraction = (px * sx + py * sy + pz * sz) / denominator;
    fraction = std::max(0., std::min(1., fraction));
    const double dx = px - sx * fraction;
    const double dy = py - sy * fraction;
    const double dz = pz - sz * fraction;
    return dx * dx + dy * dy + dz * dz;
}

bool expanded_segment_bounds(const Vec3 &point, const Vec3 &start,
                             const Vec3 &end, double radius) {
    radius = std::max(0., radius);
    for (int i = 0; i < 3; ++i) {
        const double low = std::min(start[i], end[i]) - radius;
        const double high = std::max(start[i], end[i]) + radius;
        if (point[i] < low || point[i] > high) return false;
    }
    return true;
}

struct Reflection {
    Vec3 vector = {{0., 0., 0.}};
    bool valid = false;
};
Reflection ideal_reflection(const Vec3 &velocity, const Vec3 &normal) {
    // Python's sum(generator) starts at integer 0 and adds in input order.
    double normal_sq = 0.;
    for (int i = 0; i < 3; ++i)
        normal_sq += normal[i] * normal[i];
    if (!std::isfinite(normal_sq) || normal_sq <= 1.e-24) return {};
    const double inverse_length = 1. / std::sqrt(normal_sq);
    Vec3 unit = {{0., 0., 0.}};
    for (int i = 0; i < 3; ++i)
        unit[i] = normal[i] * inverse_length;
    double projection = 0.;
    for (int i = 0; i < 3; ++i)
        projection += velocity[i] * unit[i];
    Reflection result;
    for (int i = 0; i < 3; ++i) {
        result.vector[i] = velocity[i] - 2. * projection * unit[i];
        if (!std::isfinite(result.vector[i])) return {};
    }
    result.valid = true;
    return result;
}

Vec3 ricochet_departure(const Vec3 &impact, const Vec3 &reflected,
                        const Vec3 &surface_normal) {
    // Retain the original float(value) ** 2 rather than substituting a dot
    // product; the original calculation is a separate CPython pow operation.
    volatile double exponent = 2.;
    double normal_sq = 0.;
    for (int i = 0; i < 3; ++i)
        normal_sq += std::pow(surface_normal[i], exponent);
    const double length = std::sqrt(normal_sq);
    if (length <= 1.e-12) throw Unsupported();
    Vec3 normal = {{0., 0., 0.}};
    for (int i = 0; i < 3; ++i)
        normal[i] = surface_normal[i] / length;
    double side = 0.;
    for (int i = 0; i < 3; ++i)
        side += reflected[i] * normal[i];
    const double sign = side >= 0. ? 1. : -1.;
    Vec3 result = {{0., 0., 0.}};
    for (int i = 0; i < 3; ++i)
        result[i] = impact[i] + sign * normal[i] * .002;
    return result;
}

double magnitude(PyObject *raw) {
    // Float-only copied inputs, same left-to-right sum as CPython 2.7.
    // Scalar fallback uses abs(float(gravity or 0.0)).
    if (sequence(raw)) {
        double squared = 0.;
        for (Py_ssize_t i = 0; i < size(raw); ++i) {
            const double value = finite_number(items(raw)[i]);
            squared += value * value;
        }
        return std::sqrt(squared);
    }
    if (raw == none_object) return 0.;
    return std::abs(finite_number(raw));
}

double chord_error(double gravity, double duration) {
    const double time = std::max(0., duration);
    return gravity * time * time / 8.;
}

double curvature_step(double gravity, double maximum_step,
                      double maximum_error) {
    maximum_step = std::max(.001, maximum_step);
    maximum_error = std::max(1.e-9, maximum_error);
    if (gravity <= 1.e-12) return maximum_step;
    const double error_limit = std::sqrt(8. * maximum_error / gravity);
    return std::max(.001, std::min(maximum_step, error_limit));
}

PyObject *pack_vector(const Vec3 &value) {
    OwnedTuple result(3);
    for (int i = 0; i < 3; ++i) {
        if (!std::isfinite(value[i])) throw Unsupported();
        result.set(i, float_new(value[i]));
    }
    return result.release();
}
}  // namespace projectile_spatial_law

PyObject *WOT_CDECL projectile_spatial(PyObject *, PyObject *args) {
    NATIVE_PROFILE_ENTRY(projectile_spatial);
    try {
        require_sequence(args, 3, true);
        PyObject **values = items(args);
        const int op = index_value(values[0]);
        if (op < 0 || op > 5) throw Unsupported();
        if (op == 4 || op == 5) {
            require_sequence(values[1], 1, true);
            require_sequence(values[2], op == 4 ? 1 : 4, true);
            PyObject *gravity_source = items(values[1])[0];
            const double gravity = projectile_spatial_law::magnitude(gravity_source);
            double out = 0.;
            if (op == 4) {
                const double duration = finite_number(items(values[2])[0]);
                profile.opcode(op);
                out = profile.run([&] {
                    return projectile_spatial_law::chord_error(gravity, duration);
                });
            } else {
                PyObject **a = items(values[2]);
                const double step = finite_number(a[0]);
                const double error = finite_number(a[1]);
                const double default_step = finite_number(a[2]);
                const double default_error = finite_number(a[3]);
                profile.opcode(op);
                out = profile.run([&] {
                    return projectile_spatial_law::curvature_step(
                        gravity, step == 0. ? default_step : step,
                        error == 0. ? default_error : error);
                });
            }
            if (!std::isfinite(out)) throw Unsupported();
            PyObject *object = float_new(out);
            if (!object) throw PythonAllocationFailed();
            return object;
        }
        require_sequence(values[1], op == 2 ? 2 : 3, true);
        require_sequence(values[2], op == 1 ? 1 : 0, true);
        PyObject **raw = items(values[1]);
        const auto first = projectile_spatial_law::vector(raw[0]);
        const auto second = projectile_spatial_law::vector(raw[1]);
        const auto third = op == 2 ? projectile_spatial_law::Vec3{{0., 0., 0.}} :
                                      projectile_spatial_law::vector(raw[2]);
        const double radius = op == 1 ? finite_number(items(values[2])[0]) : 0.;
        profile.opcode(op);
        if (op == 0) {
            const double result = profile.run([&] {
                return projectile_spatial_law::segment_distance_sq(first, second, third);
            });
            if (!std::isfinite(result)) throw Unsupported();
            PyObject *object = float_new(result);
            if (!object) throw PythonAllocationFailed();
            return object;
        }
        if (op == 1) {
            const bool result = profile.run([&] {
                return projectile_spatial_law::expanded_segment_bounds(
                    first, second, third, radius);
            });
            PyObject *object = int_new(result ? 1L : 0L);
            if (!object) throw PythonAllocationFailed();
            return object;
        }
        if (op == 2) {
            const auto result = profile.run([&] {
                return projectile_spatial_law::ideal_reflection(first, second);
            });
            if (result.valid) return projectile_spatial_law::pack_vector(result.vector);
            // Integer zero means a successfully evaluated invalid reflection;
            // None alone indicates unsupported input and Python fallback.
            PyObject *object = int_new(0);
            if (!object) throw PythonAllocationFailed();
            return object;
        }
        const auto result = profile.run([&] {
            return projectile_spatial_law::ricochet_departure(first, second, third);
        });
        return projectile_spatial_law::pack_vector(result);
    } catch (const PythonAllocationFailed &) {
        profile.fail();
        return 0;
    } catch (...) {
        profile.fail();
        return fallback();
    }
}
