"""Local surface connectivity, independent of slope scoring and driving laws.

Only a realised hull origin owns this context. Authored anchors and remote
goals are not physical floor observations. Unknown native queries are neither
an invented floor nor evidence of a disconnected surface.
"""
import math
from gui.mods.offline_lan_0922.worker_diagnostics import observed

RADIUS = 8.0
STEP = 1.0
MIN_STEP = .25
JOIN_ERROR = .20
QUERY_TRIGGER = .50
MAX_COLUMNS = 64


class LocalHeightLinks(object):
    def __init__(self, probe):
        self.probe = probe
        self.origin = None
        self.columns = {}
        self.results = {}
        self.receipts = []
        self._column_history = {}

    def begin(self, origin, authored=(), now=None):
        self.origin = tuple(origin)
        self.authored = set(tuple(p) for p in authored if p is not None)
        self.columns = {}
        self.results = {}
        self.receipts = []
        self.queries = 0
        self.column_evidence = []
        self.now = now
        self.generation = None
        self.cache_hits = 0

    def owns(self, start):
        return self.origin is not None and all(
            abs(float(start[i])-self.origin[i]) < .01 for i in range(3))

    @staticmethod
    def plane(surface, x, z):
        p, n = surface['point'], surface['normal']
        return p[1]-(n[0]*(x-p[0])+n[2]*(z-p[2]))/n[1]

    def column(self, x, z, low, high):
        key = (float(x), float(z), low, high)
        if key in self.columns:
            return self.columns[key]
        cached = self._column_history.get(key)
        if (self.generation is not None and self.now is not None and cached and
                cached[0] == self.generation and 0. <= self.now-cached[1] <= .5):
            self.cache_hits += 1
            self.columns[key] = cached[2]
            self._column_history[key] = (cached[0],self.now,cached[2])
            self.column_evidence.append(dict(position=(x,z),band=(low,high),
                status='complete',reused=True,surfaces=cached[2]))
            return cached[2]
        if self.queries >= MAX_COLUMNS:
            if not self.column_evidence or self.column_evidence[-1].get('status') != 'budget':
                self.column_evidence.append(dict(status='budget',position=(x,z)))
            return None
        self.queries += 1
        try:
            raw = self.probe(x, z, low, high)
            if not isinstance(raw, dict) or raw.get('status') != 'complete':
                rows = None
            else:
                if raw.get('generation') is not None:
                    self.generation = tuple(raw['generation'])
                rows = []
                for row in raw.get('surfaces', ()):
                    p, n = tuple(row['point']), tuple(row['normal'])
                    if (len(p) == len(n) == 3 and n[1] > .0001 and
                            all(not math.isnan(float(v)) and not math.isinf(float(v))
                                for v in p+n)):
                        rows.append(dict(point=p, normal=n,
                            navigation_water=bool(row.get('navigation_water',False))))
        except Exception as error:
            # Native/space teardown failures are local unknown evidence, never
            # an exception that terminates every Bot or the battle.
            query_error = '%s: %s' % (type(error).__name__,str(error)[:160])
            rows = None
        self.column_evidence.append(dict(position=(x,z),band=(low,high),
            status=(raw.get('status') if isinstance(raw,dict) else 'invalid')
                if 'raw' in locals() else 'query_error', surfaces=rows))
        if 'query_error' in locals():
            self.column_evidence[-1]['error'] = query_error
        self.columns[key] = rows
        if rows is not None and self.generation is not None and self.now is not None:
            if len(self._column_history) >= 512:
                self._column_history.pop(next(iter(self._column_history)))
            self._column_history[key] = (self.generation,self.now,rows)
        return rows

    def _join(self, a, b, low, high, samples):
        pa, pb = a['point'], b['point']
        distance = math.hypot(pb[0]-pa[0], pb[2]-pa[2])
        # Residuals between tangent planes, not a height/run or normal limit.
        left = self.plane(b, pa[0], pa[2])-pa[1]
        right = pb[1]-self.plane(a, pb[0], pb[2])
        if distance <= STEP and max(abs(left), abs(right)) <= JOIN_ERROR:
            return True
        if distance <= MIN_STEP:
            # Two terrain facets may meet at a sharp, continuous slope bend.
            # Their plane intersection inside this short interval is allowed.
            connected = max(abs(left), abs(right)) <= JOIN_ERROR or left*right <= 0.
            if not connected and len(samples) < 12:
                samples.append(dict(start=pa, end=pb, residuals=(left,right)))
            return connected
        x, z = (pa[0]+pb[0])*.5, (pa[2]+pb[2])*.5
        rows = self.column(x, z, low, high)
        if rows is None or not rows:
            return None
        unknown = False
        for mid in sorted(rows, key=lambda row:abs(
                row['point'][1]-self.plane(a,x,z))):
            first = self._join(a, mid, low, high, samples)
            if first is False:
                continue
            second = self._join(mid, b, low, high, samples)
            if first is True and second is True:
                return True
            unknown |= first is None or second is None
        return None if unknown else False

    @observed('navigation.height_link')
    def inspect(self, start, end, baked_start=None):
        start, end = tuple(start), tuple(end)
        distance = math.hypot(end[0]-start[0],end[2]-start[2])
        if not self.owns(start) or distance > RADIUS:
            return 'unscoped', end
        # This is only a query trigger. It never rejects a grade or a point.
        if (abs(end[1]-start[1]) <= QUERY_TRIGGER and
                (baked_start is None or abs(baked_start-start[1]) <= QUERY_TRIGGER)):
            return 'unchanged', end
        key = (start,end)
        if key in self.results:
            return self.results[key]
        low, high = min(start[1],end[1])-3., max(start[1],end[1])+3.
        receipt = dict(origin=start, target=end, radius=RADIUS,
            baked_origin_height=baked_start,scope='realised_pose_only',
            query_band=(low,high), step=STEP, minimum_step=MIN_STEP,
            join_error=JOIN_ERROR, query_trigger=QUERY_TRIGGER, samples=[])
        self.receipts.append(receipt)
        evidence_start = len(self.column_evidence)
        roots = self.column(start[0],start[2],low,high)
        if roots and baked_start is not None and abs(baked_start-start[1]) <= QUERY_TRIGGER:
            root = min(roots,key=lambda row:abs(row['point'][1]-start[1]))
            residual = end[1]-self.plane(root,end[0],end[2])
            if (abs(root['point'][1]-start[1]) <= QUERY_TRIGGER and
                    abs(residual) <= JOIN_ERROR):
                # Ordinary same-layer baked corridors keep their original
                # admission owner. A continuous steep plane is not a jump.
                receipt.update(status='unchanged',reason='same_layer_plane',
                    root_surface=root,residual=residual,resolved=end,
                    columns=self.queries,column_evidence=self.column_evidence[
                        evidence_start:evidence_start+16])
                self.results[key] = ('unchanged',end)
                return self.results[key]
        ends = self.column(end[0],end[2],low,high)
        status, resolved = 'unknown', end
        if roots and ends:
            root = min(roots,key=lambda row:abs(row['point'][1]-start[1]))
            receipt['root_surface'] = root
            # Root height is an accepted near-ground pose, never a remote hint.
            if abs(root['point'][1]-start[1]) <= QUERY_TRIGGER:
                alternatives, unknown = [], False
                explicit = end not in self.authored
                for surface in sorted(ends,key=lambda row:abs(row['point'][1]-root['point'][1])):
                    connected = self._join(root,surface,low,high,receipt['samples'])
                    receipt.setdefault('end_surfaces',[]).append(dict(
                        height=surface['point'][1], connected=connected,
                        navigation_water=surface.get('navigation_water',False)))
                    if connected is True:
                        alternatives.append(surface['point'])
                    unknown |= connected is None
                expected = [p for p in alternatives if abs(p[1]-end[1]) <= JOIN_ERROR]
                expected_unknown = any(s['connected'] is None and
                    abs(s['height']-end[1]) <= JOIN_ERROR
                    for s in receipt.get('end_surfaces',()))
                if expected or alternatives and not explicit:
                    status, resolved = 'connected', (expected or alternatives)[0]
                elif alternatives and not expected_unknown:
                    status, resolved = 'other_surface', alternatives[0]
                elif not unknown:
                    status = 'disconnected'
                if status in ('connected','other_surface') and any(
                        s['point'] == tuple(resolved) and s.get('navigation_water')
                        for s in ends):
                    # Resolving a lower storey cannot inherit the dry deck's
                    # water mask. The native adapter supplies the old limit.
                    status = 'water'
            else:
                receipt['unknown_reason'] = 'accepted_pose_has_no_nearby_ground'
        receipt.update(status=status,resolved=resolved,columns=self.queries,
            column_evidence=self.column_evidence[evidence_start:evidence_start+16])
        result = (status, tuple(resolved))
        self.results[key] = result
        if status in ('connected','other_surface'):
            self.results[(start,tuple(resolved))] = ('connected',tuple(resolved))
        return result
