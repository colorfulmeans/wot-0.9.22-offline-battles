"""Human-only base defence and observed-front support. No Bot scheduling."""
from __future__ import division
import math


def lane_distance(position, route):
    points = route.get('waypoints', ())
    distances = []
    for first,last in zip(points,points[1:]):
        dx,dz=last[0]-first[0],last[1]-first[1]
        length=dx*dx+dz*dz
        t=max(0.,min(1.,((position[0]-first[0])*dx+(position[2]-first[1])*dz)/length)) if length else 0.
        distances.append(math.hypot(position[0]-first[0]-t*dx,position[2]-first[1]-t*dz))
    return min(distances) if distances else float('inf')


def defence_routes(home, routes):
    # A flag centre can be occupied or have no supported navigation cell.
    # Offer nearby approach points; PlayerNavigation must still prove each
    # candidate's actual height and connected path, including bridge layers.
    points=[tuple(home)]
    points.extend((home[0]+math.sin(i*math.pi/4.)*20.,
                   home[1]+math.cos(i*math.pi/4.)*20.) for i in range(8))
    for route in routes:
        points.extend(tuple(p) for p in route.get('waypoints',())
                      if math.hypot(p[0]-home[0],p[1]-home[1])<=40.)
    unique=[]
    for point in points:
        if point not in unique:unique.append(point)
    return [dict(id='player_base_defence' if i==0 else
        'player_base_defence_approach_%s'%i,waypoints=[point])
        for i,point in enumerate(unique)]


class Strategy(object):
    def __init__(self):
        self.mode='route'
        self.clear_at=0.
        self.cooldown=0.
        self.proposal=None
        self.proposed_at=0.
        self.receipt={}

    def decide(self, now, routes, current, contacts, allies, base, home, engaged=False):
        alarm=bool(base.get('points',0)>0 or base.get('invaders',0)>0)
        if alarm and home is not None:
            self.clear_at=now+5.
            self.receipt=dict(mode='defend',points=base.get('points',0),invaders=base.get('invaders',0))
            if self.mode!='defend':
                self.mode='defend'
                return defence_routes(home,routes)
            return None
        if self.mode=='defend':
            if now<self.clear_at:return None
            self.mode='route';self.cooldown=now+20.
            self.receipt=dict(mode='rejoin_after_defence')
            return list(routes)
        if engaged or now<self.cooldown or current is None or not contacts:
            self.proposal=None
            return None
        scores={}
        for route in routes:
            enemies=sum(1 for r in contacts if lane_distance(r['position'],route)<100.)
            support=sum(1 for r in allies if r['alive'] and lane_distance(r['position'],route)<100.)
            scores[route['id']]=enemies-.25*support if enemies else 0.
        if not scores:return None
        best=max(routes,key=lambda r:(scores[r['id']],r['id']))
        if best['id']==current['id'] or scores[best['id']]<=scores.get(current['id'],0.)+1.:
            self.proposal=None
            return None
        if self.proposal!=best['id']:
            self.proposal,self.proposed_at=best['id'],now
            return None
        if now-self.proposed_at<8.:return None
        self.cooldown=now+20.;self.proposal=None
        self.receipt=dict(mode='support_observed_front',route=best['id'],scores=scores)
        return [best]
