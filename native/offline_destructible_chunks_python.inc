// Complete current tree-motion chunk candidate calculation. This is stateless:
// no streamed registry, engine callback or retained Python object is involved.
// The adapter admits only the already-reviewed #1513 pure chunk mapper.
namespace destructible_chunks_law {
using Point = std::array<double, 3>;
Point point(PyObject *object) {
    require_sequence(object, 3, true);
    Point value = {};
    for (int i = 0; i < 3; ++i) {
        value[i] = finite_number(items(object)[i]);
        if (std::abs(value[i]) > 1.e6) throw Unsupported();
    }
    return value;
}
struct AxisSamples { double minimum, span; int segments; };
AxisSamples samples(double minimum, double maximum, double chunk_size) {
    const double span = maximum - minimum;
    const double count = std::ceil(span / (chunk_size * .5));
    if (!std::isfinite(count)) throw Unsupported();
    if (count > 32.) return {minimum, span, 33};
    return {minimum, span, static_cast<int>(std::max(1., count))};
}
double sample(const AxisSamples &axis, int index) {
    // Do not use lerp, repeated additions or reassociate the original formula.
    return axis.minimum + axis.span * double(index) / double(axis.segments);
}
int chunk(double x, double z) {
    // Math.Vector3 stores both mapper inputs as float32 before the reference
    // promotes them for its floor(value * .01) and integer wire calculation.
    volatile float fx = static_cast<float>(x), fz = static_cast<float>(z);
    const double gx = std::floor(double(fx) * .01);
    const double gz = std::floor(double(fz) * .01);
    // This is admission only, not a clamp or a changed world boundary.
    if (gx < -127. || gx > 126. || gz < -127. || gz > 126.) throw Unsupported();
    return ((static_cast<int>(gx) + 127) << 8) | (static_cast<int>(gz) + 127);
}
struct Result { int status = 1; std::set<int> chunks; };
Result query(PyObject *boxes, double radius, double chunk_size) {
    Result result;
    for (Py_ssize_t i = 0; i < size(boxes); ++i) {
        PyObject *box = items(boxes)[i];
        require_sequence(box, 2);
        const Point center = point(items(box)[0]);
        PyObject *axes = items(box)[1];
        require_sequence(axes, 0);
        // Prepared swept hulls use three or four generators. Unsupported
        // unprepared geometry remains owned by the original reference law.
        if (size(axes) > 4) throw Unsupported();
        double rx = 0., rz = 0.;
        for (Py_ssize_t j = 0; j < size(axes); ++j) {
            const Point axis = point(items(axes)[j]);
            rx += std::abs(axis[0]);
            rz += std::abs(axis[2]);
        }
        const auto xs = samples((center[0] - rx) - radius,
                                (center[0] + rx) + radius, chunk_size);
        const auto zs = samples((center[2] - rz) - radius,
                                (center[2] + rz) + radius, chunk_size);
        if (xs.segments > 32 || zs.segments > 32)
            return {2, {}}; // Same hard result, before any later box is read.
        for (int x = 0; x <= xs.segments; ++x)
            for (int z = 0; z <= zs.segments; ++z)
                result.chunks.insert(chunk(sample(xs, x), sample(zs, z)));
    }
    result.status = result.chunks.empty() ? 1 : 0;
    return result;
}
}
PyObject *WOT_CDECL destr_required_chunks(PyObject *, PyObject *args) {
    NATIVE_PROFILE_ENTRY(destr_query);
    profile.opcode(8);
    try {
        require_sequence(args, 2, true);
        PyObject **a = items(args);
        require_sequence(a[0], 0);
        require_sequence(a[1], 2, true);
        const double radius = finite_number(items(a[1])[0]);
        const double size = finite_number(items(a[1])[1]);
        if (size == 0. || std::abs(size) > 1.e6 || std::abs(radius) > 1.e6)
            throw Unsupported();
        const auto result = profile.run([&] {
            return destructible_chunks_law::query(a[0], radius, size);
        });
        OwnedTuple out(2), chunks(result.chunks.size());
        size_t i = 0;
        for (int chunk : result.chunks) chunks.set(i++, int_new(chunk));
        out.set(0, int_new(result.status));
        out.set(1, chunks.release());
        return out.release();
    } catch (const PythonAllocationFailed &) {
        profile.fail(); return 0;
    } catch (...) {
        profile.fail(); return fallback();
    }
}
