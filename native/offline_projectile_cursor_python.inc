// Remaining current-release trajectory/range/substep numerics. The already
// installed chord, moving-target, spatial and mesh operations keep their IDs.
// Borrow plain inputs synchronously; never retain an engine or Python object.
namespace projectile_cursor_law {
using Point = projectile_math_law::Point;
Point point(PyObject *value) {
    require_sequence(value, 3);
    return {{finite_number(items(value)[0]), finite_number(items(value)[1]),
             finite_number(items(value)[2])}};
}
double scalar(PyObject *value) {
    if (value == none_object) return 0.;
    const double result = finite_number(value);
    return result == 0. ? 0. : result; // Python float(value or 0.0).
}
PyObject *pack(const Point &point) {
    if (!projectile_math_law::finite(point)) throw Unsupported();
    OwnedTuple result(3);
    for (size_t i = 0; i < 3; ++i) result.set(i, float_new(point[i]));
    return result.release();
}
using Boundary = std::array<double, 2>;
std::vector<Boundary> boundaries(double cursor, double end, double step) {
    if (cursor < 0. || end < cursor || step < .001) throw Unsupported();
    std::vector<Boundary> result;
    result.reserve(64);
    while (cursor + 1.e-9 < end && result.size() < 64) {
        const double next = std::min(end, cursor + step);
        if (next <= cursor) throw Unsupported();
        result.push_back({{cursor, next}});
        cursor = next;
    }
    return result; // Temporary batch size is not a limit on total flight time.
}
PyObject *pack(const std::vector<Boundary> &rows) {
    OwnedTuple result(rows.size());
    for (size_t i = 0; i < rows.size(); ++i) {
        OwnedTuple pair(2);
        pair.set(0, float_new(rows[i][0]));
        pair.set(1, float_new(rows[i][1]));
        result.set(i, pair.release());
    }
    return result.release();
}
template <class Profile>
PyObject *run(int op, PyObject *vectors, PyObject *scalars, Profile &profile) {
    if (op == 35) {
        require_sequence(vectors, 0, true);
        require_sequence(scalars, 3, true);
        const double cursor = finite_number(items(scalars)[0]);
        const double end = finite_number(items(scalars)[1]);
        const double step = finite_number(items(scalars)[2]);
        return pack(profile.run([&] { return boundaries(cursor, end, step); }));
    }
    require_sequence(vectors, op == 33 ? 3 : 2, true);
    require_sequence(scalars, op == 32 ? 0 : 1, true);
    const Point a = point(items(vectors)[0]), b = point(items(vectors)[1]);
    if (op == 32) {
        const double value = profile.run([&] {
            const double dx = b[0]-a[0], dy = b[1]-a[1], dz = b[2]-a[2];
            return std::sqrt(dx*dx + dy*dy + dz*dz);
        });
        if (!std::isfinite(value)) throw Unsupported();
        PyObject *result = float_new(value);
        if (!result) throw PythonAllocationFailed();
        return result;
    }
    const double amount = scalar(items(scalars)[0]);
    if (op == 33) {
        const Point c = point(items(vectors)[2]);
        return pack(profile.run([&] {
            return projectile_math_law::trajectory(a, b, c, amount);
        }));
    }
    if (op == 34)
        return pack(profile.run([&] { return projectile_math_law::lerp(a,b,amount); }));
    throw Unsupported();
}
} // namespace projectile_cursor_law
