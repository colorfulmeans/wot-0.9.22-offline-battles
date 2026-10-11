// Current-release traffic braking geometry. Borrowed inputs, no callbacks,
// engine access, state ownership or cross-call caches. Opcodes 3 and 4 share
// the existing driver_geometry frontier and are separated by the caller's
// one lazy stopping-distance callback.
namespace traffic_geometry_law {
using Axis = driver_geometry_law::Axis;
struct Row {
    double x = 0., y = 0., z = 0., yaw = 0., vx = 0., vz = 0.;
    double width = 0., length = 0., low = 0., high = 0.;
    double pitch = 0., roll = 0.;
    bool has_y = false, has_shape = false, has_interval = false;
    Py_ssize_t index = 0;
};

double optional(PyObject *row, Field key, double default_value) {
    PyObject *value = field(row, key);
    return value ? finite_number(value) : default_value;
}

Row row_values(PyObject *object, bool motion, bool require_dimensions = false) {
    if (!plain_dict(object)) throw Unsupported();
    Row row;
    PyObject *position = field(object, POSITION);
    require_sequence(position, 3, true);
    row.x = finite_number(items(position)[0]);
    row.z = finite_number(items(position)[2]);
    row.has_y = !absent(items(position)[1]);
    if (row.has_y) row.y = finite_number(items(position)[1]);
    PyObject *shape = field(object, SHAPE);
    row.has_shape = !absent(shape);
    if (row.has_shape) {
        require_sequence(shape, 2);
        row.width = finite_number(items(shape)[0]);
        row.length = finite_number(items(shape)[1]);
        row.has_interval = size(shape) >= 4;
        if (row.has_interval) {
            row.low = finite_number(items(shape)[2]);
            row.high = finite_number(items(shape)[3]);
            row.pitch = optional(object, PITCH, 0.);
            row.roll = optional(object, ROLL, 0.);
        }
    } else if (require_dimensions) {
        row.width = finite_number(field(object, DRIVER_HALF_WIDTH));
        row.length = finite_number(field(object, DRIVER_HALF_LENGTH));
    } else {
        // _dimensions uses defaults only for absent keys, not false values.
        row.width = optional(object, DRIVER_HALF_WIDTH, 1.7);
        row.length = optional(object, DRIVER_HALF_LENGTH, 3.5);
    }
    if (motion) {
        row.yaw = finite_number(field(object, YAW));
        PyObject *velocity = field(object, VELOCITY);
        if (velocity) {
            require_sequence(velocity, 3, true);
            row.vx = finite_number(items(velocity)[0]);
            row.vz = finite_number(items(velocity)[2]);
        }
    }
    return row;
}

std::array<double, 2> interval(const Row &row) {
    const double cp = std::cos(row.pitch), sp = std::sin(row.pitch);
    const double cr = std::cos(row.roll), sr = std::sin(row.roll);
    const double up = cp * cr;
    const double center = row.y + (row.low + row.high) * .5 * up;
    const double extent = (std::abs(cp * sr) * row.width +
                           std::abs(sp) * row.length +
                           std::abs(up) * (row.high - row.low) * .5);
    return {{center - extent, center + extent}};
}

bool same_level(const Row &a, const Row &b) {
    if (!a.has_shape || !b.has_shape || !a.has_y || !b.has_y) return true;
    if (!a.has_interval || !b.has_interval) throw Unsupported();
    const auto x = interval(a), y = interval(b);
    return std::min(x[1], y[1]) - std::max(x[0], y[0]) > 0.;
}

struct Prepared {
    std::array<double, 6> values;
    std::vector<Py_ssize_t> peers, candidates;
};

Prepared prepare(const Row &own, const std::vector<Row> &rows, double throttle) {
    const double sine = std::sin(own.yaw), cosine = std::cos(own.yaw);
    const double speed = own.vx * sine + own.vz * cosine;
    const double sign = (throttle < -.01 ||
                         (std::abs(throttle) <= .01 && speed < 0.)) ? -1. : 1.;
    const Axis axis = {sine * sign, cosine * sign};
    Prepared result;
    result.values = {{speed, sign, own.x, own.z, axis.x, axis.z}};
    for (const auto &peer : rows) {
        if (!same_level(own, peer)) continue;
        result.peers.push_back(peer.index);
        const double dx = peer.x - own.x, dz = peer.z - own.z;
        if (dx * axis.x + dz * axis.z <= 0.) continue;
        const double reach = (own.length + own.width) + (peer.length + peer.width);
        if (std::hypot(dx, dz) > reach + std::max(2., speed * speed)) continue;
        result.candidates.push_back(peer.index);
    }
    return result;
}

PyObject *index_tuple(const std::vector<Py_ssize_t> &indices) {
    PyObject *out = tuple_new(static_cast<Py_ssize_t>(indices.size()));
    if (!out) return 0;
    for (size_t i = 0; i < indices.size(); ++i) {
        items(out)[i] = int_new(static_cast<long>(indices[i]));
        if (!items(out)[i]) { decref(out); return 0; }
    }
    return out;
}

PyObject *pack(const Prepared &result) {
    PyObject *out = tuple_new(3);
    if (!out) return 0;
    items(out)[0] = tuple_new(6);
    if (!items(out)[0]) { decref(out); return 0; }
    for (size_t i = 0; i < result.values.size(); ++i) {
        items(items(out)[0])[i] = float_new(result.values[i]);
        if (!items(items(out)[0])[i]) { decref(out); return 0; }
    }
    items(out)[1] = index_tuple(result.peers);
    if (!items(out)[1]) { decref(out); return 0; }
    items(out)[2] = index_tuple(result.candidates);
    if (!items(out)[2]) { decref(out); return 0; }
    return out;
}

template <class Profile>
PyObject *prepare_call(PyObject *source, PyObject *raw, PyObject *tuning,
                       Profile &profile) {
    require_sequence(tuning, 1, true);
    require_sequence(raw, 0);
    const double throttle = finite_number(items(tuning)[0]);
    const Row own = row_values(source, true);
    const auto own_id = identity(field(source, ID));
    PyObject *own_team = field(source, TEAM);
    if (!absent(own_team)) identity(own_team);
    std::vector<Row> rows;
    rows.reserve(static_cast<size_t>(size(raw)));
    for (Py_ssize_t i = 0; i < size(raw); ++i) {
        PyObject *peer = items(raw)[i];
        if (!plain_dict(peer)) throw Unsupported();
        if (identity(field(peer, ID)) == own_id) continue;
        PyObject *alive = field(peer, ALIVE);
        if (alive && (alive == none_object || finite_number(alive) == 0.)) continue;
        PyObject *team = field(peer, TEAM);
        if (!absent(own_team) && !absent(team) &&
                identity(team) != identity(own_team)) continue;
        Row row = row_values(peer, false);
        row.index = i;
        rows.push_back(row);
    }
    return pack(profile.run([&] { return prepare(own, rows, throttle); }));
}

std::array<Axis, 2> axes(const Row &row) {
    const double s = std::sin(row.yaw), c = std::cos(row.yaw);
    return {{{c, -s}, {s, c}}};
}

double radius(const Row &row, const std::array<Axis, 2> &basis, Axis n) {
    return std::abs(basis[0].x * n.x + basis[0].z * n.z) * row.width +
           std::abs(basis[1].x * n.x + basis[1].z * n.z) * row.length;
}

bool contact_time(const Row &own, const Row &peer, Axis own_velocity,
                  double horizon, double prediction, double epsilon) {
    const auto a = axes(own), b = axes(peer);
    const std::array<Axis, 4> directions = {{a[0], a[1], b[0], b[1]}};
    const double dx = peer.x - own.x, dz = peer.z - own.z;
    const double vx = peer.vx * horizon - own_velocity.x;
    const double vz = peer.vz * horizon - own_velocity.z;
    double enter = 0., leave = prediction;
    for (auto n : directions) {
        const double distance = dx * n.x + dz * n.z;
        const double rate = vx * n.x + vz * n.z;
        const double r = radius(own, a, n) + radius(peer, b, n);
        if (std::abs(rate) <= epsilon) {
            if (std::abs(distance) >= r) return false;
            continue;
        }
        const double start = (-r - distance) / rate, end = (r - distance) / rate;
        enter = std::max(enter, std::min(start, end));
        leave = std::min(leave, std::max(start, end));
        if (enter >= leave) return false;
    }
    return true;
}

long blocker(const Row &own, const std::vector<Row> &rows, const double *v) {
    // v: pre-callback x/z, axis x/z, speed, step, braking distance,
    // current prediction window and contact epsilon. The body's current
    // position/yaw/shape and every candidate are reread after that callback.
    const double distance = std::min(80., v[6]) + std::abs(v[4]) * v[5] + .12;
    const double horizon = std::min(1., std::max(v[5],
        2. * std::min(v[6], 80.) / std::max(std::abs(v[4]), .1)));
    const Axis velocity = {v[2] * distance, v[3] * distance};
    for (const auto &peer : rows) {
        const driver_geometry_law::Peer other = {peer.x, peer.y, peer.z,
            peer.yaw, peer.length, peer.width, false, peer.index};
        const auto contact = driver_geometry_law::contact(
            v[0], v[1], own.yaw, own.length, own.width, other);
        if (contact[2] >= -1.e-9) {
            if (v[2] * contact[0] + v[3] * contact[1] >= -1.e-9) continue;
            return static_cast<long>(peer.index);
        }
        if (contact_time(own, peer, velocity, horizon, v[7], v[8]))
            return static_cast<long>(peer.index);
    }
    return -1;
}

template <class Profile>
PyObject *blocker_call(PyObject *source, PyObject *raw, PyObject *tuning,
                       Profile &profile) {
    require_sequence(raw, 0);
    require_sequence(tuning, 9, true);
    double v[9];
    for (int i = 0; i < 9; ++i) v[i] = finite_number(items(tuning)[i]);
    if (v[7] < 0. || v[8] < 0.) throw Unsupported();
    Row own = row_values(source, true, true);
    std::vector<Row> rows;
    rows.reserve(static_cast<size_t>(size(raw)));
    for (Py_ssize_t i = 0; i < size(raw); ++i) {
        Row peer = row_values(items(raw)[i], true, true);
        peer.index = i;
        rows.push_back(peer);
    }
    return int_new(profile.run([&] { return blocker(own, rows, v); }));
}
} // namespace traffic_geometry_law
