// Complete current mesh consumers. Existing ray/nearest/cone kernels remain
// the oracle primitives; this layer removes Python hit-group round trips.
// All input objects are borrowed only during this synchronous GIL-held call.
namespace internal_mesh_volume_law {
namespace q = internal_mesh_query_law;
namespace c = internal_mesh_cone_law;
using Point = q::Point;
using Interval = std::array<double, 2>;
struct Volume {
    q::Mesh mesh;
    PyObject *orientations;
    bool closed;
    Point low, high;
    explicit Volume(PyObject *raw) : mesh(raw, 7) {
        auto g = items(raw);
        orientations = g[3];
        if (g[4]->ob_type != bool_type) throw Unsupported();
        closed = number(g[4]) != 0.;
        low = q::point(g[5]); high = q::point(g[6]);
    }
};
bool contains(const Volume &v, const Point &p, double epsilon) {
    if (!v.closed) return false;
    for (int i = 0; i < 3; ++i)
        if (p[i] < v.low[i] - epsilon || p[i] > v.high[i] + epsilon)
            return false;
    const Point direction = {{1., .3713906763541037, .52999894000318}};
    const double infinity = std::numeric_limits<double>::infinity();
    const auto hits = q::line_hits(v.mesh, v.orientations, p, direction,
                                  -infinity, infinity, epsilon);
    size_t count = 0;
    for (const auto &hit : hits.groups) {
        if (std::abs(hit.t) <= epsilon) return true;
        if (hit.t > 0. && (hit.mask == 1 || hit.mask == 2)) ++count;
    }
    return count % 2 != 0;
}
struct Intervals { std::vector<Interval> values; long tested = 0; };
Intervals intervals(const Volume &v, const Point &start, const Point &end,
                    double epsilon) {
    Intervals result;
    const Point delta = q::sub(end, start);
    if (!q::line_box(start, delta, v.low, v.high, 0., 1., epsilon)) return result;
    if (q::dot(delta, delta) < 1.e-24) {
        if (contains(v, start, epsilon)) result.values.push_back({{0., 1.}});
        return result;
    }
    const double infinity = std::numeric_limits<double>::infinity();
    const auto hits = q::line_hits(v.mesh, v.orientations, start, delta,
        v.closed ? -infinity : 0., v.closed ? infinity : 1., epsilon);
    result.tested = hits.tested;
    if (!v.closed) {
        for (const auto &hit : hits.groups) {
            const double t = std::max(0., std::min(1., hit.t));
            result.values.push_back({{t, t}});
        }
        return result;
    }
    bool has_entry = false;
    double entry = 0.;
    for (const auto &hit : hits.groups) {
        if (hit.mask != 1 && hit.mask != 2) {
            if (0. <= hit.t && hit.t <= 1.) result.values.push_back({{hit.t, hit.t}});
            continue;
        }
        if (!has_entry) { entry = hit.t; has_entry = true; }
        else {
            const double low = std::max(0., entry), high = std::min(1., hit.t);
            if (low <= high) result.values.push_back({{low, high}});
            has_entry = false;
        }
    }
    std::stable_sort(result.values.begin(), result.values.end(),
        [](const Interval &a, const Interval &b) {
            return a[0] != b[0] ? a[0] < b[0] : a[1] < b[1];
        });
    return result;
}
PyObject *pack(const Intervals &result) {
    OwnedTuple out(2), rows(result.values.size());
    for (size_t i = 0; i < result.values.size(); ++i) {
        OwnedTuple row(2);
        row.set(0, float_new(result.values[i][0]));
        row.set(1, float_new(result.values[i][1]));
        rows.set(i, row.release());
    }
    out.set(0, rows.release()); out.set(1, int_new(result.tested));
    return out.release();
}
struct Distance {
    q::DistanceResult nearest;
    bool inside = false;
};
PyObject *pack(const Distance &result) {
    OwnedTuple out(5);
    out.set(0, float_new(result.inside ? 0. : std::sqrt(result.nearest.squared)));
    if (!result.inside && result.nearest.found) {
        OwnedTuple point(3);
        for (int i = 0; i < 3; ++i) point.set(i, float_new(result.nearest.closest[i]));
        out.set(1, point.release());
    } else out.set(1, fallback());
    out.set(2, integer_result(result.nearest.vertex));
    out.set(3, int_new(result.nearest.tested));
    out.set(4, int_new(result.inside ? 1L : 0L));
    return out.release();
}
template<class Profile>
PyObject *run(int op, PyObject *geometry, PyObject *parameters, Profile &profile) {
    if (op == 8) {
        // Caller has already established a positive exact primitive distance.
        // Do not repeat containment or replace the current 14-step search.
        const q::Mesh mesh(geometry);
        require_sequence(parameters, 5, true);
        auto p = items(parameters);
        const Point apex = c::point(p[0]), axis = c::point(p[1]);
        const double depth = finite_number(p[2]), tangent = finite_number(p[3]);
        const double epsilon = finite_number(p[4]);
        if (std::abs(depth) > 1.e6 || std::abs(tangent) > 1.e6 ||
            std::abs(epsilon) > 1.e6) throw Unsupported();
        const auto result = profile.run([&] {
            if (!c::query(mesh.vertices, mesh.faces, mesh.root,
                          apex, axis, depth, tangent, epsilon).hit)
                return std::array<double, 2>{{0., 0.}};
            double low = 0., high = depth;
            for (int i = 0; i < 14; ++i) {
                const double middle = (low + high) * .5;
                if (c::query(mesh.vertices, mesh.faces, mesh.root,
                             apex, axis, middle, tangent, epsilon).hit) high = middle;
                else low = middle;
            }
            return std::array<double, 2>{{1., high}};
        });
        OwnedTuple out(2);
        out.set(0, int_new(result[0] != 0. ? 1L : 0L));
        out.set(1, float_new(result[1]));
        return out.release();
    }
    if (op < 5 || op > 7) throw Unsupported();
    require_sequence(parameters, op == 6 ? 3 : 2, true);
    const Volume volume(geometry);
    const Point first = q::point(items(parameters)[0]);
    const double epsilon = finite_number(items(parameters)[op == 6 ? 2 : 1]);
    if (std::abs(epsilon) > 1.e6) throw Unsupported();
    if (op == 5) {
        const bool result = profile.run([&] { return contains(volume, first, epsilon); });
        PyObject *out = int_new(result ? 1L : 0L);
        if (!out) throw PythonAllocationFailed();
        return out;
    }
    if (op == 6) {
        const Point last = q::point(items(parameters)[1]);
        return pack(profile.run([&] { return intervals(volume, first, last, epsilon); }));
    }
    return pack(profile.run([&] {
        Distance result;
        result.inside = contains(volume, first, epsilon);
        if (!result.inside) result.nearest = q::nearest(volume.mesh, first);
        return result;
    }));
}
} // namespace internal_mesh_volume_law
