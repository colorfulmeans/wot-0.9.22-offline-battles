// Current 0.10.0 friendly-traffic crossing calculations. These are pure,
// synchronous pair operations: no persistent leases, Python references,
// callbacks, collision engine, or actor state is retained by native code.
namespace traffic_crossing_law {
using traffic_geometry_law::Axis;
using traffic_geometry_law::Row;
using traffic_geometry_law::row_values;
using traffic_geometry_law::axes;
using traffic_geometry_law::radius;

inline double dot(Axis a, Axis b) { return a.x * b.x + a.z * b.z; }
inline double cross(Axis a, Axis b) { return a.x * b.z - a.z * b.x; }
inline Axis subtract(Axis a, Axis b) { return {a.x - b.x, a.z - b.z}; }
inline Axis pos(const Row &r) { return {r.x, r.z}; }
inline Axis velocity(const Row &r) { return {r.vx, r.vz}; }
inline Axis side(Axis a) { return {a.z, -a.x}; }

struct Actor { Row row; int64_t id; };
Actor actor(PyObject *o, bool motion) {
    Actor result;
    result.id = identity(field(o, ID));
    result.row = row_values(o, motion, true);
    return result;
}

struct Travel { Axis axis; double speed; };
Travel travel(const Row &body, double epsilon) {
    const Axis v = velocity(body);
    const double speed = std::hypot(v.x, v.z);
    if (speed > epsilon) return {{v.x / speed, v.z / speed}, speed};
    return {axes(body)[1], 0.};
}

// Lexicographic _arrival tuple exactly: (kind, time_or_distance, actor ID).
struct Arrival { int kind; double value; int64_t id; };
Arrival arrival(const Actor &body, Axis axis, double speed, Axis gate,
                double reference, double epsilon) {
    const Axis delta = subtract(gate, pos(body.row));
    const double distance = dot(delta, axis);
    const double front_distance = distance - radius(body.row, axes(body.row), axis);
    if (front_distance <= 0.) return {0, front_distance, body.id};
    const double pace = speed > epsilon ? speed : reference;
    return {1, pace > epsilon ? front_distance / pace :
               std::numeric_limits<double>::infinity(), body.id};
}
bool less(Arrival a, Arrival b) {
    if (a.kind != b.kind) return a.kind < b.kind;
    if (a.value != b.value) return a.value < b.value;
    return a.id < b.id;
}

struct BeginResult {
    int mode = 0;  // 0: no crossing, 1: head-on, 2: yield
    Axis axis = {0., 0.};
    double until = 0., target_first = 0., target_second = 0.;
    int64_t winner = 0;
    double clear_after = 0.;
};
BeginResult begin(const Actor &a, const Actor &b, bool held_a, bool held_b,
                  const double *v) {
    // v: now, prediction horizon, yield lease, head-on offset, epsilon.
    const double now = v[0], prediction = v[1], lease = v[2];
    const double offset = v[3], epsilon = v[4];
    const Axis forward_a = axes(a.row)[1], forward_b = axes(b.row)[1];
    if (dot(velocity(a.row), forward_a) < -epsilon ||
        dot(velocity(b.row), forward_b) < -epsilon) return {};
    const Travel at = travel(a.row, epsilon), bt = travel(b.row, epsilon);
    const double alignment = dot(at.axis, bt.axis);
    if (alignment >= std::cos(.35)) return {};
    const bool has_contact = traffic_geometry_law::contact_time(
        a.row, b.row, velocity(a.row), 1., prediction, epsilon);
    const Axis delta = subtract(pos(b.row), pos(a.row));
    if (alignment <= -std::cos(.60)) {
        const double ahead = dot(delta, at.axis);
        const double second_ahead = -dot(delta, bt.axis);
        const Axis perpendicular = side(at.axis);
        const double lateral = std::abs(dot(delta, perpendicular));
        const double width = radius(a.row, axes(a.row), perpendicular) +
                             radius(b.row, axes(b.row), perpendicular);
        const double gap = ahead - radius(a.row, axes(a.row), at.axis) -
                           radius(b.row, axes(b.row), at.axis);
        if (ahead <= 0. || second_ahead <= 0. || lateral >= width ||
            (!has_contact && gap > width * .5)) return {};
        BeginResult result;
        result.mode = 1;
        result.axis = at.axis;
        result.until = now + lease;
        result.target_first = a.row.yaw + offset;
        result.target_second = b.row.yaw + offset;
        return result;
    }
    if (!has_contact) return {};
    const double denominator = cross(at.axis, bt.axis);
    if (std::abs(denominator) <= epsilon) return {};
    const double d = cross(delta, bt.axis) / denominator;
    const Axis gate = {a.row.x + at.axis.x * d,
                       a.row.z + at.axis.z * d};
    const double pace = std::max(at.speed, bt.speed);
    const Arrival rank_a = arrival(a, at.axis, at.speed, gate,
                                   held_a ? pace : 0., epsilon);
    const Arrival rank_b = arrival(b, bt.axis, bt.speed, gate,
                                   held_b ? pace : 0., epsilon);
    const bool second_wins = less(rank_b, rank_a);
    const Actor &winner = second_wins ? b : a;
    const Actor &loser = second_wins ? a : b;
    const Axis axis = second_wins ? bt.axis : at.axis;
    BeginResult result;
    result.mode = 2;
    result.axis = axis;
    result.until = now + lease;
    result.winner = winner.id;
    result.clear_after = dot(gate, axis) +
        radius(winner.row, axes(winner.row), axis) +
        radius(loser.row, axes(loser.row), axis);
    return result;
}

PyObject *pack(const BeginResult &result) {
    if (result.mode == 0) return int_new(0); // Supported: no crossing.
    PyObject *out = tuple_new(8);
    if (!out) return 0;
    PyObject **values = items(out);
    values[0] = int_new(result.mode);
    values[1] = float_new(result.axis.x);
    values[2] = float_new(result.axis.z);
    values[3] = float_new(result.until);
    values[4] = float_new(result.target_first);
    values[5] = float_new(result.target_second);
    values[6] = int_new(static_cast<long>(result.winner));
    values[7] = float_new(result.clear_after);
    for (int i = 0; i < 8; ++i) {
        if (!values[i]) { decref(out); return 0; }
    }
    return out;
}

template <class Profile>
PyObject *begin_call(PyObject *pair, PyObject *flags, PyObject *tuning,
                     Profile &profile) {
    require_sequence(pair, 2, true);
    require_sequence(flags, 2, true);
    require_sequence(tuning, 5, true);
    double v[5];
    for (int i = 0; i < 5; ++i) v[i] = finite_number(items(tuning)[i]);
    if (v[1] < 0. || v[4] < 0.) throw Unsupported();
    int held_a = index_value(items(flags)[0]);
    int held_b = index_value(items(flags)[1]);
    if (held_a < 0 || held_a > 1 || held_b < 0 || held_b > 1) throw Unsupported();
    const Actor a = actor(items(pair)[0], true);
    const Actor b = actor(items(pair)[1], true);
    return pack(profile.run([&] { return begin(a, b, held_a != 0, held_b != 0, v); }));
}

bool cleared(const Actor &first, const Actor &second,
             int mode, int64_t winner, Axis axis, double threshold) {
    if (mode == 1) {
        const Row &body = first.id == winner ? first.row : second.row;
        return dot(pos(body), axis) > threshold;
    }
    const Axis delta = subtract(pos(second.row), pos(first.row));
    const Axis perpendicular = side(axis);
    return dot(delta, axis) <= 0. ||
           std::abs(dot(delta, perpendicular)) >=
              radius(first.row, axes(first.row), perpendicular) +
              radius(second.row, axes(second.row), perpendicular);
}

template <class Profile>
PyObject *cleared_call(PyObject *pair, PyObject *flags, PyObject *unused,
                       Profile &profile) {
    require_sequence(pair, 2, true);
    require_sequence(flags, 5, true);
    require_sequence(unused, 0, true);
    const int mode = index_value(items(flags)[0]);
    if (mode < 0 || mode > 1) throw Unsupported();
    const int64_t winner = identity(items(flags)[1]);
    Axis axis = {finite_number(items(flags)[2]), finite_number(items(flags)[3])};
    const double threshold = finite_number(items(flags)[4]);
    const Actor a = actor(items(pair)[0], true), b = actor(items(pair)[1], true);
    return int_new(profile.run([&] { return cleared(a,b,mode,winner,axis,threshold) ? 1L : 0L; }));
}

double separation(const Row &first, const Row &second) {
    const auto aa = axes(first), bb = axes(second);
    const Axis delta = subtract(pos(second), pos(first));
    const std::array<Axis,4> directions = {{aa[0], aa[1], bb[0], bb[1]}};
    double greatest = -std::numeric_limits<double>::infinity();
    for (const Axis axis : directions) {
        const double gap = std::abs(dot(delta,axis)) -
                           radius(first,aa,axis) - radius(second,bb,axis);
        if (gap > greatest) greatest = gap;
    }
    return greatest;
}

template <class Profile>
PyObject *separation_call(PyObject *pair, PyObject *unused1, PyObject *unused2,
                          Profile &profile) {
    require_sequence(pair, 2, true);
    require_sequence(unused1, 0, true);
    require_sequence(unused2, 0, true);
    const Row a = row_values(items(pair)[0], true, true);
    const Row b = row_values(items(pair)[1], true, true);
    return float_new(profile.run([&] { return separation(a,b); }));
}

template <class Profile>
PyObject *adjust_roster_call(PyObject *source, PyObject *raw,
                             PyObject *unused, Profile &profile) {
    require_sequence(raw, 0);
    require_sequence(unused, 0, true);
    if (!plain_dict(source)) throw Unsupported();
    const int64_t own_id = identity(field(source,ID));
    PyObject *own_team = field(source,TEAM);
    const bool own_team_absent = absent(own_team);
    int64_t own_team_id = 0;
    if (!own_team_absent) own_team_id = identity(own_team);
    const Row own = row_values(source,false);
    std::vector<Py_ssize_t> matches;
    matches.reserve(static_cast<size_t>(size(raw)));
    for (Py_ssize_t i = 0; i < size(raw); ++i) {
        PyObject *peer = items(raw)[i];
        if (!plain_dict(peer)) throw Unsupported();
        if (identity(field(peer,ID)) == own_id) continue;
        PyObject *alive = field(peer,ALIVE);
        if (alive && (alive == none_object || finite_number(alive) == 0.)) continue;
        PyObject *team = field(peer,TEAM);
        if (own_team_absent != absent(team)) continue;
        if (!own_team_absent && identity(team) != own_team_id) continue;
        const Row row = row_values(peer,false);
        if (traffic_geometry_law::same_level(own,row)) matches.push_back(i);
    }
    return traffic_geometry_law::index_tuple(profile.run([&] {return matches;}));
}
} // namespace traffic_crossing_law
