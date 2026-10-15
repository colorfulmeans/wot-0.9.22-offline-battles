// Current-release local-driver geometry. No strategy or engine ownership.
namespace driver_geometry_law {
struct Peer { double x,y,z,yaw,length,width; bool stationary; Py_ssize_t index; };
struct Axis { double x,z; };
std::array<Axis,2> axes(double yaw) {
    return {{{std::sin(yaw),std::cos(yaw)},{std::cos(yaw),-std::sin(yaw)}}};
}
bool overlaps(double x,double z,double yaw,double length,double width,const Peer &b) {
    const auto a=axes(yaw),bb=axes(b.yaw);
    const std::array<Axis,4> directions={{a[0],a[1],bb[0],bb[1]}};
    const double dx=b.x-x,dz=b.z-z;
    for(const auto &n:directions) {
        const double distance=std::abs(dx*n.x+dz*n.z);
        const double ra=std::abs(a[0].x*n.x+a[0].z*n.z)*length+
                        std::abs(a[1].x*n.x+a[1].z*n.z)*width;
        const double rb=std::abs(bb[0].x*n.x+bb[0].z*n.z)*b.length+
                        std::abs(bb[1].x*n.x+bb[1].z*n.z)*b.width;
        if(distance>ra+rb)return false;
    }
    return true;
}
std::array<double,3> contact(double x,double z,double yaw,double length,double width,const Peer &b) {
    const auto a=axes(yaw),bb=axes(b.yaw);
    const std::array<Axis,4> directions={{a[1],a[0],bb[1],bb[0]}};
    const double dx=x-b.x,dz=z-b.z;std::array<double,3> best={{0.,0.,0.}};bool first=true;
    for(auto n:directions) {
        const double ra=width*std::abs(n.x*a[1].x+n.z*a[1].z)+length*std::abs(n.x*a[0].x+n.z*a[0].z);
        const double rb=b.width*std::abs(n.x*bb[1].x+n.z*bb[1].z)+b.length*std::abs(n.x*bb[0].x+n.z*bb[0].z);
        const double signed_distance=dx*n.x+dz*n.z;
        const double overlap=ra+rb-std::abs(signed_distance);
        if(first || overlap<best[2]) {
            if(signed_distance<0.){n.x=-n.x;n.z=-n.z;}
            best={{n.x,n.z,overlap}};first=false;
        }
    }
    return best;
}
double dimension(PyObject *row,Field key,double fallback_value) {
    PyObject *value=field(row,key);
    if(absent(value))return fallback_value;
    const double result=finite_number(value);return result==0.?fallback_value:result;
}
}
#include "offline_traffic_geometry_python.inc"
#include "offline_traffic_crossing_python.inc"
#include "offline_driver_candidates_python.inc"

PyObject *WOT_CDECL driver_geometry(PyObject *,PyObject *args) {
    NATIVE_PROFILE_ENTRY(driver_geometry);
    try {
        require_sequence(args,4,true);auto a=items(args);const int op=index_value(a[0]);
        if(op==3)return traffic_geometry_law::prepare_call(a[1],a[2],a[3],profile);
        if(op==4)return traffic_geometry_law::blocker_call(a[1],a[2],a[3],profile);
        if(op==5)return traffic_crossing_law::begin_call(a[1],a[2],a[3],profile);
        if(op==6)return traffic_crossing_law::cleared_call(a[1],a[2],a[3],profile);
        if(op==7)return traffic_crossing_law::separation_call(a[1],a[2],a[3],profile);
        if(op==8)return traffic_crossing_law::adjust_roster_call(a[1],a[2],a[3],profile);
        if(op==9) { profile.opcode(op); return driver_candidates_law::run(a[1],a[2],a[3],profile); }
        if((op<0 || op>2) && op!=10)throw Unsupported();
        profile.opcode(op);
        require_sequence(a[1],7,true);double v[7];for(int i=0;i<7;++i)v[i]=finite_number(items(a[1])[i]);
        require_sequence(a[2],0);require_sequence(a[3],0);
        std::vector<double> fractions;for(Py_ssize_t i=0;i<size(a[3]);++i)fractions.push_back(finite_number(items(a[3])[i]));
        std::vector<driver_geometry_law::Peer> peers;peers.reserve(size(a[2]));
        for(Py_ssize_t i=0;i<size(a[2]);++i) {
            PyObject *row=items(a[2])[i],*where=row;bool stationary=true;
            double yaw=0.,length=v[4],width=v[5];
            if(plain_dict(row)) {
                where=field(row,POSITION);if(absent(where))where=field(row,DRIVER_POS);
                if(absent(where))continue;
                if(op==1) {
                    PyObject *alive=field(row,ALIVE);
                    if(!absent(alive) && alive->ob_type!=bool_type)throw Unsupported();
                    if(absent(alive) || number(alive)!=0.) {
                        PyObject *velocity=field(row,VELOCITY);if(absent(velocity))continue;
                        require_sequence(velocity,3,true);
                        stationary=std::hypot(finite_number(items(velocity)[0]),finite_number(items(velocity)[2]))<=.65;
                        if(!stationary)continue;
                    }
                }
                yaw=driver_geometry_law::dimension(row,YAW,0.);
                length=driver_geometry_law::dimension(row,DRIVER_HALF_LENGTH,v[4]);
                width=driver_geometry_law::dimension(row,DRIVER_HALF_WIDTH,v[5]);
            } else if(op==1) {
                if(row->ob_type!=tuple_type && row->ob_type!=list_type)throw Unsupported();
                continue;
            }
            require_sequence(where,3,true);
            driver_geometry_law::Peer p={finite_number(items(where)[0]),finite_number(items(where)[1]),
                finite_number(items(where)[2]),yaw,length,width,stationary,i};
            if(std::abs(p.y-v[1])<=5.)peers.push_back(p);
        }
        if(op==10) {
            const auto counts=profile.run([&] {
                std::array<long,2> result={{0,0}};
                for(int side=0;side<2;++side) {
                    const double amount=(side==0?-1.:1.)*v[6];
                    for(const auto &p:peers)for(double f:fractions) {
                        if(driver_geometry_law::overlaps(
                                v[0],v[2],v[3]+amount*f,v[4],v[5],p)) {
                            if(result[side]==std::numeric_limits<long>::max())throw Unsupported();
                            ++result[side];
                        }
                    }
                }
                return result;
            });
            OwnedTuple out(2);
            out.set(0,int_new(counts[0]));out.set(1,int_new(counts[1]));
            return out.release();
        }
        const long result=profile.run([&]()->long {
            using namespace driver_geometry_law;
            if(op==2) {
                long occupied=0;
                for(const auto &p:peers)for(double f:fractions)
                    if(overlaps(v[0],v[2],v[3]+v[6]*f,v[4],v[5],p))++occupied;
                return occupied;
            }
            const double sign=op==0?-1.:1.;
            const double sx=v[0]+sign*std::sin(v[3])*v[6]*.5;
            const double sz=v[2]+sign*std::cos(v[3])*v[6]*.5;
            for(const auto &p:peers) {
                if(op==0 || op==1) {
                    const auto hit=contact(v[0],v[2],v[3],v[4],v[5],p);
                    if(hit[2]>=-1.e-9) {
                        const double bx=sign*std::sin(v[3]),bz=sign*std::cos(v[3]);
                        const double outward=bx*hit[0]+bz*hit[1];
                        const double away=bx*(v[0]-p.x)+bz*(v[2]-p.z);
                        if(outward>=-1.e-9 && away>=-1.e-9)continue;
                    }
                }
                if(overlaps(sx,sz,v[3],v[4]+v[6]*.5,v[5],p))return op==0?p.index:1;
            }
            return op==0?-1:0;
        });return int_new(result);
    }catch(const PythonAllocationFailed &){profile.fail();return 0;}
     catch(...){profile.fail();return fallback();}
}
