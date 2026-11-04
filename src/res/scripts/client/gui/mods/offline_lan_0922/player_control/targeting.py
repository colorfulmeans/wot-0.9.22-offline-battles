"""Player-local target priorities from visible contacts and accepted hits.

This does not discover entities, request Bot intelligence, or grant a firing
lane. It ranks the foreground client's already-visible candidates; ordered
aim-point and ammunition proofs remain the separate engagement owner's job.
"""
from __future__ import division
import math


RECENT_ATTACKER_SECONDS = 6.
CLOSE_THREAT_DISTANCE = 60.


class TargetSelection(object):
    def __init__(self):
        self.recent_hits = {}
        self.receipt = dict(reason='no_visible_target', selected=None)

    def reset(self):
        self.recent_hits.clear()
        self.receipt = dict(reason='released', selected=None)

    def attacked(self, identity, now):
        if identity is not None:
            self.recent_hits[identity] = float(now)
            if len(self.recent_hits) > 16:
                oldest = min(self.recent_hits, key=self.recent_hits.get)
                del self.recent_hits[oldest]

    def rank(self, contacts, position, current, now, home=None, base=None, mission=None):
        self.recent_hits = dict((identity, at) for identity, at in self.recent_hits.items()
                                if 0. <= now - at <= RECENT_ATTACKER_SECONDS)
        base = base or {}
        mission = mission or {}
        defend = mission.get('action') == 'defend_base' and mission.get('status') not in (
            'failed', 'cancelled')
        alarm = base.get('points', 0) > 0 or base.get('invaders', 0) > 0
        rows = []
        for contact in contacts:
            point, identity = contact.get('position'), contact.get('id')
            if (identity is None or point is None or not contact.get('visible', True) or
                    not contact.get('alive', True) or contact.get('health', 1) <= 0):
                continue
            span = math.hypot(point[0] - position[0], point[2] - position[2])
            health = max(0., min(1., float(contact.get('health', 1)) /
                                max(1., float(contact.get('max_health', 1)))))
            near = span <= CLOSE_THREAT_DISTANCE
            retaliate = identity in self.recent_hits
            at_base = home is not None and math.hypot(point[0] - home[0], point[2] - home[1]) <= 100.
            invader = bool(at_base and (alarm or defend))
            # A close threat outranks a distant retaliation target. Base
            # defence outranks incidental long-range damage farming. There is
            # deliberately no Bot difficulty/human-opponent preference.
            urgency = 3 if near else 2 if invader else 1 if retaliate else 0
            score = (1. - health) * 35. + max(0., 500. - span) * .10
            if retaliate:
                score += 40. * (1. - (now - self.recent_hits[identity]) / RECENT_ATTACKER_SECONDS)
            rows.append(dict(id=identity, urgency=urgency, score=score, distance=span,
                             near=near, retaliate=retaliate, invader=invader))
        rows.sort(key=lambda row: (-row['urgency'], -row['score'], str(row['id'])))
        previous = next((row for row in rows if row['id'] == current), None)
        best = rows[0] if rows else None
        preempt = bool(previous is not None and best is not None and best['id'] != current and
                       (best['urgency'] > previous['urgency'] or
                        best['urgency'] == previous['urgency'] > 0 and
                        best['score'] > previous['score'] + 45.))
        # Ordinary priority differences choose a new acquisition or a proven
        # alternative, but do not repeatedly throw away ordered-point progress.
        if previous is not None and not preempt:
            rows.remove(previous)
            rows.insert(0, previous)
        selected = rows[0] if rows else None
        reason = ('no_visible_target' if selected is None else
                  'close_threat' if selected['near'] else
                  'base_invader' if selected['invader'] else
                  'recent_attacker' if selected['retaliate'] else
                  'preserve_ordered_lock' if previous is selected else 'visible_priority')
        self.receipt = dict(selected=selected['id'] if selected is not None else None,
                            preempt=preempt, reason=reason, priorities=rows[:16])
        return [row['id'] for row in rows], preempt
