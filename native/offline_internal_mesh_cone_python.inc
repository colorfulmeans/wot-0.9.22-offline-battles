// Current internal_mesh.intersects_cone surface query, including the entire
// BVH walk and clipped-triangle quadratic. No mesh is rebuilt, cached, or
// retained. Borrowed plain containers are read synchronously under the GIL.
namespace internal_mesh_cone_law {
using Point = std::array<double, 3>;

Point sub(const Point &a, const Point &b) {
    return {{a[0] - b[0], a[1] - b[1], a[2] - b[2]}};
}
double dot(const Point &a, const Point &b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}
Point add_scaled(const Point &a, const Point &b, double scale) {
    return {{a[0] + b[0] * scale, a[1] + b[1] * scale,
             a[2] + b[2] * scale}};
}

Point point(PyObject *value) {
    require_sequence(value, 3, true);
    Point result = {};
    for (int i = 0; i < 3; ++i) {
        result[i] = finite_number(items(value)[i]);
        // Admission bound only: unusual inputs retain the Python law. This
        // keeps intermediate quadratics finite, never clamps geometry.
        if (std::abs(result[i]) > 1.e6) throw Unsupported();
    }
    return result;
}

std::vector<Point> clip(const std::vector<Point> &polygon, const Point &axis,
                        double limit, bool above) {
    std::vector<Point> result;
    if (polygon.empty()) return result;
    result.reserve(polygon.size() + 1);
    Point previous = polygon.back();
    double prev = dot(previous, axis) - limit;
    for (const Point &current : polygon) {
        const double now = dot(current, axis) - limit;
        const bool before = above ? prev >= 0. : prev <= 0.;
        const bool after = above ? now >= 0. : now <= 0.;
        if (before != after)
            result.push_back(add_scaled(previous, sub(current, previous),
                                        prev / (prev - now)));
        if (after) result.push_back(current);
        previous = current;
        prev = now;
    }
    return result;
}

bool triangle(Point a, Point b, Point c, const Point &apex, const Point &axis,
              double depth, double tangent, double epsilon) {
    a = sub(a, apex); b = sub(b, apex); c = sub(c, apex);
    auto polygon = clip({a, b, c}, axis, 0., true);
    polygon = clip(polygon, axis, depth, false);
    if (polygon.empty()) return false;
    const double k = 1. + tangent * tangent;
    const auto quadratic = [&](const Point &p, const Point &q) {
        return dot(p, q) - k * dot(p, axis) * dot(q, axis);
    };
    const double tolerance = 1.e-10;
    for (size_t i = 0; i < polygon.size(); ++i) {
        const Point &p = polygon[i];
        const double f = quadratic(p, p);
        if (f <= tolerance) return true;
        const Point edge = sub(polygon[(i + 1) % polygon.size()], p);
        const double aa = quadratic(edge, edge), bb = quadratic(p, edge);
        if (aa > 0.) {
            const double t = std::max(0., std::min(1., -bb / aa));
            if (f + 2. * t * bb + t * t * aa <= tolerance) return true;
        }
    }
    const Point e1 = sub(b, a), e2 = sub(c, a);
    const double aa = quadratic(e1, e1), bb = quadratic(e1, e2);
    const double cc = quadratic(e2, e2);
    const double det = aa * cc - bb * bb;
    if (aa > 0. && det > 1.e-18) {
        const double l1 = quadratic(a, e1), l2 = quadratic(a, e2);
        const double u = (bb * l2 - cc * l1) / det;
        const double v = (bb * l1 - aa * l2) / det;
        if (u >= -epsilon && v >= -epsilon && u + v <= 1. + epsilon) {
            const Point p = add_scaled(add_scaled(a, e1, u), e2, v);
            const double axial = dot(p, axis);
            if (-epsilon <= axial && axial <= depth + epsilon &&
                    quadratic(p, p) <= tolerance) return true;
        }
    }
    return false;
}

Py_ssize_t sequence_index(PyObject *value, Py_ssize_t count) {
    // Use only the bridge's reviewed builtin integer decoder, not __index__.
    const auto index = identity(value);
    if (index < 0 || index >= count) throw Unsupported();
    return static_cast<Py_ssize_t>(index);
}

struct Result { bool hit; long tested; };
Result query(PyObject *vertices, PyObject *faces, PyObject *root,
             const Point &apex, const Point &axis,
             double depth, double tangent, double epsilon) {
    const Point base = add_scaled(apex, axis, depth);
    Point low = {}, high = {};
    for (int a = 0; a < 3; ++a) {
        // The reference uses ** 2, not a normalized/approximated axis.
        const double radius = depth * tangent *
            std::sqrt(std::max(0., 1. - std::pow(axis[a], 2.)));
        low[a] = std::min(apex[a], base[a] - radius);
        high[a] = std::max(apex[a], base[a] + radius);
    }
    std::vector<PyObject *> stack(1, root);
    Result result = {false, 0};
    size_t visited = 0;
    const size_t maximum_nodes = 2 * static_cast<size_t>(size(faces)) + 1;
    while (!stack.empty()) {
        // A prepared binary BVH has at most 2*faces-1 nodes. Reject malformed
        // cycles/DAG expansions without retaining pointers after this call.
        if (++visited > maximum_nodes) throw Unsupported();
        PyObject *node = stack.back(); stack.pop_back();
        require_sequence(node, 5, true);
        PyObject **fields = items(node);
        const Point minimum = point(fields[0]), maximum = point(fields[1]);
        bool outside = false;
        for (int a = 0; a < 3; ++a) {
            if (minimum[a] > high[a] + epsilon || maximum[a] < low[a] - epsilon) {
                outside = true; break;
            }
        }
        if (outside) continue;
        if (fields[2] != none_object) {
            stack.push_back(fields[2]);
            stack.push_back(fields[3]); // Same right-first LIFO walk as Python.
            continue;
        }
        PyObject *indices = fields[4];
        require_sequence(indices, 0);
        for (Py_ssize_t j = 0; j < size(indices); ++j) {
            // Prevent a malformed leaf from overflowing the packed count.
            if (result.tested == std::numeric_limits<long>::max()) throw Unsupported();
            ++result.tested;
            const auto face_index = sequence_index(items(indices)[j], size(faces));
            PyObject *face = items(faces)[face_index];
            require_sequence(face, 3, true);
            Point values[3];
            for (int i = 0; i < 3; ++i) {
                const auto vertex_index = sequence_index(items(face)[i], size(vertices));
                values[i] = point(items(vertices)[vertex_index]);
            }
            if (triangle(values[0], values[1], values[2], apex, axis,
                         depth, tangent, epsilon)) {
                result.hit = true; return result;
            }
        }
    }
    return result;
}

template<class Profile>
PyObject *run(PyObject *geometry, PyObject *parameters, Profile &profile) {
    require_sequence(geometry, 3, true);
    require_sequence(parameters, 5, true);
    PyObject **g = items(geometry), **p = items(parameters);
    require_sequence(g[0], 0);
    require_sequence(g[1], 0);
    const Point apex = point(p[0]), axis = point(p[1]);
    const double depth = finite_number(p[2]), tangent = finite_number(p[3]);
    const double epsilon = finite_number(p[4]);
    if (std::abs(depth) > 1.e6 || std::abs(tangent) > 1.e6 ||
            std::abs(epsilon) > 1.e6) throw Unsupported();
    const auto result = profile.run([&] {
        return query(g[0], g[1], g[2], apex, axis, depth, tangent, epsilon);
    });
    PyObject *out = tuple_new(2);
    if (!out) return 0;
    items(out)[0] = int_new(result.hit ? 1L : 0L);
    if (!items(out)[0]) { decref(out); return 0; }
    items(out)[1] = int_new(result.tested);
    if (!items(out)[1]) { decref(out); return 0; }
    return out;
}
} // namespace internal_mesh_cone_law
