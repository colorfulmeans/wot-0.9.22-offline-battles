// Pure current-release laws. No engine object or actor state is retained.
namespace release_ground {
constexpr double pi=3.14159265358979323846;
double bleed(double v,double budget) {
    return budget<=0.?v:v>budget?v-budget:v< -budget?v+budget:0.;
}
std::array<double,2> extrema(double a,double b,double start,double end) {
    double lo=std::min(a*std::cos(start)+b*std::sin(start),a*std::cos(end)+b*std::sin(end));
    double hi=std::max(a*std::cos(start)+b*std::sin(start),a*std::cos(end)+b*std::sin(end));
    const double stationary=std::atan2(b,a);
    const int first=static_cast<int>(std::ceil((start-stationary)/pi));
    const int last=static_cast<int>(std::floor((end-stationary)/pi));
    for(int i=first;i<=last;++i) {
        const double angle=stationary+i*pi,value=a*std::cos(angle)+b*std::sin(angle);
        lo=std::min(lo,value);hi=std::max(hi,value);
    }
    return {{lo,hi}};
}
double interval_min(double a,double b,double start,double end,double drift) {
    const double delta=end-start,radius=std::hypot(a,b);
    double result=std::min(a*std::cos(start)+b*std::sin(start),a*std::cos(end)+b*std::sin(end)+drift);
    if(std::abs(delta)*radius<=1.e-15)return result;
    const double rhs= -drift/(delta*radius);
    if(rhs< -1. || rhs>1.)return result;
    const double phase=std::atan2(-a,b),alpha=std::acos(rhs),lo=std::min(start,end),hi=std::max(start,end);
    for(double root:{phase+alpha,phase-alpha}) {
        const int first=static_cast<int>(std::ceil((lo-root)/(2.*pi)));
        const int last=static_cast<int>(std::floor((hi-root)/(2.*pi)));
        for(int cycle=first;cycle<=last;++cycle) {
            const double angle=root+cycle*2.*pi,t=(angle-start)/delta;
            if(t>=0. && t<=1.)result=std::min(result,a*std::cos(angle)+b*std::sin(angle)+drift*t);
        }
    }
    return result;
}
}

PyObject *WOT_CDECL rotation_envelope(PyObject *,PyObject *args) {
    NATIVE_PROFILE_ENTRY(rotation_envelope);
    try {
        require_sequence(args,3,true);auto **a=items(args);require_sequence(a[0],2);
        double low[3],high[3];world_array(items(a[0])[0],low,3);world_array(items(a[0])[1],high,3);
        const double angle=std::abs(finite_number(a[1])),pivot=finite_number(a[2]);
        if(angle>release_ground::pi)throw Unsupported();
        for(unsigned i=0;i<3;++i)if(low[i]>high[i])throw Unsupported();
        auto value=profile.run([&] {
            std::array<double,6> out={{std::numeric_limits<double>::infinity(),low[1],
                std::numeric_limits<double>::infinity(),-std::numeric_limits<double>::infinity(),high[1],
                -std::numeric_limits<double>::infinity()}};
            for(double x:{low[0],high[0]})for(double z:{low[2],high[2]}) {
                auto rx=release_ground::extrema(x-pivot,z,-angle,angle);
                auto rz=release_ground::extrema(z,pivot-x,-angle,angle);
                out[0]=std::min(out[0],rx[0]+pivot);out[3]=std::max(out[3],rx[1]+pivot);
                out[2]=std::min(out[2],rz[0]);out[5]=std::max(out[5],rz[1]);
            }
            return out;
        });
        OwnedTuple result(2);result.set(0,world_numbers(value.data(),3));result.set(1,world_numbers(value.data()+3,3));
        return result.release();
    }catch(const PythonAllocationFailed &){profile.fail();return 0;}catch(...){profile.fail();return fallback();}
}

PyObject *WOT_CDECL rotation_departure(PyObject *,PyObject *args) {
    NATIVE_PROFILE_ENTRY(rotation_departure);
    try {
        require_sequence(args,10,true);auto **a=items(args);
        double position[3],low[3],high[3],angles[2],pose[3],travel[2],point[3],normal[3];
        world_array(a[0],position,3);world_array(a[1],low,3);world_array(a[2],high,3);
        world_array(a[3],angles,2);world_array(a[4],pose,3);world_array(a[5],travel,2);
        const double pivot=finite_number(a[6]),gradient=finite_number(a[9]);
        world_array(a[7],point,3);world_array(a[8],normal,3);
        if(std::abs(angles[0])>1.e6 || std::abs(angles[1]-angles[0])>2.*release_ground::pi || gradient<=0.)throw Unsupported();
        for(unsigned i=0;i<3;++i)if(low[i]>high[i])throw Unsupported();
        auto value=profile.run([&] {
            if(normal[1]< -.2 || std::abs(pose[1])<.1)return std::array<int,2>{{0,0}};
            const double sine=std::sin(angles[0]),cosine=std::cos(angles[0]);
            const double dx=point[0]-position[0],dy=point[1]-position[1],dz=point[2]-position[2];
            const double local[3]={dx*cosine-dz*sine,0.,dx*sine+dz*cosine};
            const double y=(dy-local[0]*pose[0]-local[2]*pose[2])/pose[1];
            const bool inside=low[0]-.001<=local[0] && local[0]<=high[0]+.001 &&
                low[1]-.001<=y && y<=high[1]+.001 && low[2]-.001<=local[2] && local[2]<=high[2]+.001;
            double before=std::numeric_limits<double>::infinity(),after=before,swept=before;
            const double drift=travel[0]*normal[0]+travel[1]*normal[2];
            const double constant=pivot*(normal[0]*cosine-normal[2]*sine);
            for(double x:{low[0],high[0]})for(double cy:{low[1],high[1]})for(double z:{low[2],high[2]}) {
                const double px=x-pivot,aa=normal[0]*px+normal[2]*z,bb=normal[0]*z-normal[2]*px;
                const double height=normal[1]*(x*pose[0]+cy*pose[1]+z*pose[2]);
                before=std::min(before,aa*cosine+bb*sine+constant+height);
                after=std::min(after,aa*std::cos(angles[1])+bb*std::sin(angles[1])+constant+height+drift);
                swept=std::min(swept,release_ground::interval_min(aa,bb,angles[0],angles[1],drift)+constant+height);
            }
            const double length=std::pow(normal[0]*normal[0]+normal[1]*normal[1]+normal[2]*normal[2],.5);
            const bool drivable=length>0. && normal[1]/length>=1./std::pow(1.+gradient*gradient,.5);
            return std::array<int,2>{{(after>before+1.e-8 || (drivable && after>=before-1.e-8)) && swept>=before-1.e-8,inside}};
        });
        OwnedTuple result(2);result.set(0,int_new(value[0]));result.set(1,int_new(value[1]));return result.release();
    }catch(const PythonAllocationFailed &){profile.fail();return 0;}catch(...){profile.fail();return fallback();}
}

PyObject *WOT_CDECL contact_ground(PyObject *,PyObject *args) {
    NATIVE_PROFILE_ENTRY(contact_ground);
    try {
        require_sequence(args,4,true);auto **a=items(args);const int op=index_value(a[0]);profile.opcode(op);
        if(op<0 || op>2 || !plain_dict(a[1]))throw Unsupported();
        require_sequence(a[2],op==0?3:op==1?7:9,true);require_sequence(a[3],8,true);
        double v[9]={},t[8];world_array(a[2],v,size(a[2]));world_array(a[3],t,8);
        const double mass=finite_number(field(a[1],MASS)),friction=finite_number(field(a[1],PH_FRICTION));
        double terrain[3];world_array(field(a[1],PH_TERRAIN),terrain,3);
        const int iterations=index_value(items(a[3])[7]);
        int index=op==0?index_value(items(a[2])[1]):op==1?index_value(items(a[2])[5]):0;
        if(index<0)index+=3;
        if(index<0 || index>2 || t[4]<=t[3] || iterations<0 || iterations>1024 || mass<0.)throw Unsupported();
        if(op==2 && (v[4]<=0. || v[5]<=0.))throw Unsupported();
        auto result=profile.run([&] {
            const double ny=op==0?v[2]:op==1?v[6]:v[7],clamped=std::max(0.,std::min(1.,ny));
            const double side=clamped>=t[4]?t[6]:clamped<=t[3]?t[5]:t[5]+(clamped-t[3])/(t[4]-t[3])*(t[6]-t[5]);
            const double roll=mass*friction*t[1]*terrain[index]/std::max(mass,1.);
            const double hold=t[2]*t[0]*std::max(ny,.1);
            const bool rolling=op==0?v[0]!=0.:op==1?v[4]!=0.:false;
            const double longitudinal=rolling?roll:std::max(hold,roll),lateral=std::max(t[2]*side*t[0]*std::max(ny,.1),roll);
            if(op==0)return std::array<double,3>{{longitudinal,lateral,0.}};
            if(op==1) {
                if(v[3]<=0.)return std::array<double,3>{{v[0],v[1],0.}};
                const double sine=std::sin(v[2]),cosine=std::cos(v[2]);
                const double f=release_ground::bleed(v[0]*sine+v[1]*cosine,longitudinal*v[3]);
                const double r=release_ground::bleed(v[0]*cosine-v[1]*sine,lateral*v[3]);
                return std::array<double,3>{{f*sine+r*cosine,f*cosine-r*sine,0.}};
            }
            if(v[8]!=0. || v[6]<=0.)return std::array<double,3>{{v[0],v[1],v[2]}};
            const double inertia=(v[4]*v[4]+v[5]*v[5])/3.,sine=std::sin(v[3]),cosine=std::cos(v[3]);
            double velocity[3]={v[0]*sine+v[1]*cosine,v[0]*cosine-v[1]*sine,v[2]},impulses[8]={};
            for(int iteration=0;iteration<iterations;++iteration) {
                double largest=0.;unsigned row=0;
                for(double x:{-v[4],v[4]})for(double z:{-v[5]/2.,v[5]/2.})for(unsigned axis=0;axis<2;++axis,++row) {
                    const double lever=axis==0?x:-z,budget=(axis==0?longitudinal:lateral)*v[6]/4.;
                    const double slip=velocity[axis]+lever*velocity[2],delta= -slip/(1.+lever*lever/inertia);
                    const double updated=std::max(-budget,std::min(budget,impulses[row]+delta)),change=updated-impulses[row];
                    impulses[row]=updated;velocity[axis]+=change;velocity[2]+=change*lever/inertia;
                    largest=std::max(largest,std::abs(change));
                }
                if(largest<1.e-9)break;
            }
            for(double &value:velocity)if(std::abs(value)<1.e-9)value=0.;
            return std::array<double,3>{{velocity[0]*sine+velocity[1]*cosine,velocity[0]*cosine-velocity[1]*sine,velocity[2]}};
        });
        return world_numbers(result.data(),op==2?3:2);
    }catch(const PythonAllocationFailed &){profile.fail();return 0;}catch(...){profile.fail();return fallback();}
}
