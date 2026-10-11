// Current LocalDriver steering-fan ranking. No engine calls or retained state.
// The Python owner commits expired keys only after complete native admission.
namespace driver_candidates_law {
struct Failure { int64_t key; double expires; bool active; };
struct Candidate { double score; double yaw; };
struct Ranked {
    std::vector<Candidate> candidates;
    std::vector<int64_t> expired;
};

double plain_float(PyObject *value) {
    if (!value || value->ob_type != float_type) throw Unsupported();
    return finite_number(value);
}
int64_t yaw_key(double yaw, double pi, int count) {
    const double turn = pi * 2.;
    double from_anchor = std::fmod(yaw + pi, turn);
    if (from_anchor < 0.) from_anchor += turn;
    else if (from_anchor == 0.) from_anchor = 0.;
    const double rounded = std::floor(from_anchor * count / turn + .5);
    if (!std::isfinite(rounded) || rounded < 0. || rounded > count + 1.)
        throw Unsupported();
    return static_cast<int64_t>(rounded) % count;
}
Ranked rank(const double *v, int buckets, const std::vector<double> &offsets,
            std::vector<Failure> failures) {
    Ranked result;
    result.candidates.reserve(offsets.size());
    for (const double offset : offsets) {
        const double candidate = v[0] + offset;
        const int64_t key = yaw_key(candidate, v[5], buckets);
        double penalty = 0.;
        for (auto &failure : failures) {
            if (!failure.active || failure.key != key) continue;
            if (failure.expires <= v[1]) {
                failure.active = false;
                result.expired.push_back(key);
            } else penalty = 3. + (failure.expires - v[1]) / v[2];
            break;
        }
        double score = std::abs(offset) + penalty;
        if (v[3] > v[1] && offset * v[4] < -.01) score += 1.25;
        if (!std::isfinite(score)) throw Unsupported();
        result.candidates.push_back({score, candidate});
    }
    std::stable_sort(result.candidates.begin(), result.candidates.end(),
        [](const Candidate &a, const Candidate &b) { return a.score < b.score; });
    return result;
}
template<class Profile>
PyObject *run(PyObject *scalars, PyObject *raw_offsets, PyObject *raw_failures,
              Profile &profile) {
    require_sequence(scalars, 7, true);
    require_sequence(raw_offsets, 0);
    require_sequence(raw_failures, 0);
    double v[6];
    for (int i = 0; i < 6; ++i) v[i] = plain_float(items(scalars)[i]);
    const int buckets = index_value(items(scalars)[6]);
    if (v[2] <= 0. || v[5] <= 0. || v[5] > 1.e6 ||
            std::abs(v[0]) > 1.e6 || buckets <= 0 || buckets > 1000000)
        throw Unsupported();
    std::vector<double> offsets;
    offsets.reserve(static_cast<size_t>(size(raw_offsets)));
    for (Py_ssize_t i = 0; i < size(raw_offsets); ++i) {
        const double value = plain_float(items(raw_offsets)[i]);
        if (std::abs(value) > 1.e6) throw Unsupported();
        offsets.push_back(value);
    }
    std::vector<Failure> failures;
    failures.reserve(static_cast<size_t>(size(raw_failures)));
    for (Py_ssize_t i = 0; i < size(raw_failures); ++i) {
        PyObject *row = items(raw_failures)[i]; require_sequence(row, 2, true);
        const auto key = identity(items(row)[0]);
        for (const auto &previous : failures)
            if (previous.key == key) throw Unsupported();
        PyObject *expires = items(row)[1];
        const bool active = expires != none_object;
        failures.push_back({key, active ? plain_float(expires) : 0., active});
    }
    const auto result = profile.run([&] { return rank(v, buckets, offsets, failures); });
    OwnedTuple out(2), candidates(result.candidates.size()), expired(result.expired.size());
    for (size_t i = 0; i < result.candidates.size(); ++i) {
        OwnedTuple row(2);
        row.set(0, float_new(result.candidates[i].score));
        row.set(1, float_new(result.candidates[i].yaw));
        candidates.set(i, row.release());
    }
    for (size_t i = 0; i < result.expired.size(); ++i)
        expired.set(i, integer_result(result.expired[i]));
    out.set(0, candidates.release()); out.set(1, expired.release());
    return out.release();
}
} // namespace driver_candidates_law
