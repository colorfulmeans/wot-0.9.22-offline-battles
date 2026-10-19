"""Bounded ordered part search; no RNG, engine queries or motion ownership."""
import math


def distance(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def angle(a, b):
    return abs((a - b + math.pi) % (2.0 * math.pi) - math.pi)


def stale_reason(row, origin, point, pose, part, now, shell, max_age=0.5):
    if row is None:
        return 'unchecked'
    if row['shell'] != shell:
        return 'shell_changed'
    threshold = min(0.5, max(0.1, distance(origin, point) * 0.005))
    if distance(row['origin'], origin) > threshold:
        return 'source_moved'
    if distance(row['point'], point) > threshold:
        return 'point_moved'
    keys = ('yaw', 'pitch', 'roll') + (('turret_yaw',) if part == 'turret' else ())
    if any(angle(row['pose'].get(k, 0.0), pose.get(k, 0.0)) > math.pi / 60.0
           for k in keys):
        return 'pose_changed'
    if now < row['at'] or now - row['at'] >= max_age:
        return 'age'
    return None


class OrderedSearch(object):
    def __init__(self, count):
        self.rows = [None] * count
        self.cursor = 0
        self.refresh = 0
        self.visited = set()
        self.last_at = None
        self.max_age = 0.5

    def step(self, origin, points, pose, shell, now, selected, probe):
        """Use at most two queries, reserving forward progress during refresh.

        A positive retained point is checked first and kept, regardless of
        earlier preferences. Searching never rolls back its unvisited cursor.
        Stale higher-priority negatives cannot authorize a lower-priority pick.
        """
        count = len(points)
        if self.last_at is not None and now > self.last_at:
            # A slow worker must be able to finish a nine-point sweep before
            # age alone expires its first negative. Pose invalidation remains
            # immediate; positive selections are always queried again.
            self.max_age = max(0.5, min(3.0, (count + 1) * (now-self.last_at)))
        self.last_at = now
        checked = []
        invalidations = []

        def check(index):
            part, point = points[index]
            reason = stale_reason(self.rows[index], origin, point, pose,
                                  part, now, shell, self.max_age)
            if reason:
                invalidations.append((index, reason))
            value = probe(index, point)
            self.rows[index] = dict(value, origin=tuple(origin), point=point,
                pose=dict((k, pose.get(k, 0.0)) for k in
                          ('yaw', 'pitch', 'roll', 'turret_yaw')),
                at=now, shell=shell)
            self.visited.add(index)
            checked.append(index)
            return value

        if selected is not None:
            value = check(selected)
            if value['clear'] and value['score'] is not None and value['score'] > 0:
                return selected, self.trace('retained', checked, invalidations, now)

        # Always advance one unseen candidate even while earlier evidence
        # changes. Geometry invalidation never resets this cursor.
        while self.cursor < count and self.cursor in self.visited:
            self.cursor += 1
        if self.cursor < count and len(checked) < 2:
            check(self.cursor)
            self.cursor += 1

        def freshness(index):
            return stale_reason(self.rows[index], origin, points[index][1],
                                pose, points[index][0], now, shell, self.max_age)

        while len(checked) < 2:
            positive = next((i for i, row in enumerate(self.rows)
                if row and row['clear'] and row['score'] is not None and
                row['score'] > 0), count)
            pending = [i for i in range(positive + (positive < count))
                       if i not in checked and freshness(i)]
            if not pending and positive < count and positive not in checked:
                pending = [positive]
            if not pending:
                pending = [i for i in range(self.cursor, count) if i not in checked]
            if not pending:
                pending = [i for i in range(count) if i not in checked and freshness(i)]
            if not pending and len(self.visited) == count:
                pending = [i for i, row in enumerate(self.rows)
                           if row and row['clear'] and i not in checked][:1]
            if not pending:
                break
            # Once the first sweep finishes, cycle rather than restarting on
            # the first two expired points forever in an all-blocked scene.
            index = (min(pending, key=lambda i: (i-self.refresh) % count)
                     if positive == count and self.cursor >= count else pending[0])
            check(index)
            self.refresh = (index + 1) % count
            while self.cursor < count and self.cursor in self.visited:
                self.cursor += 1

        for index, row in enumerate(self.rows):
            if freshness(index):
                break
            if row['clear'] and row['score'] is not None and row['score'] > 0:
                if index in checked:
                    return index, self.trace('ordered', checked, invalidations, now)
                break
        if len(self.visited) == count and not any(
                row and row['clear'] and row['score'] is not None and row['score'] > 0
                for row in self.rows):
            # Original exposed-part fallback: unknown armour is not proof of
            # penetration, and an all-zero round must not disable all firing.
            for index, row in enumerate(self.rows):
                if row['clear'] and index in checked and not freshness(index):
                    return index, self.trace('exposed_fallback', checked, invalidations, now)
        blocked = all(row and not row['clear'] and not freshness(i)
                      for i, row in enumerate(self.rows))
        return None, self.trace('blocked' if blocked else 'searching',
                                checked, invalidations, now)

    def trace(self, outcome, checked, invalidations, now):
        return dict(outcome=outcome, checked=checked, invalidations=invalidations,
            next_unvisited=self.cursor, evidence_age_limit=self.max_age,
            rows=[None if row is None else dict(
                clear=row['clear'], score=row['score'], reason=row.get('reason'),
                reachable=row.get('reachable'), point=row['point'],
                origin=row['origin'], pose=row['pose'], sampled_at=row['at'],
                age=max(0.0, now-row['at']))
                for row in self.rows])
