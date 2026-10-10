// Current release math, with no engine calls or physical state ownership.
namespace release_drive_law {
struct Law {
    double t[26], mass, power, ratio, forward, reverse, friction, brake, rotation, terrain[3];
    double clamp(double v,double lo,double hi) const {return std::max(lo,std::min(hi,v));}
    double grip(double pitch) const {
        const double ny=std::cos(pitch); double c=t[2];
        if(ny<t[3])c-=t[4]*std::pow(t[3]-ny,t[5]);
        if(ny<t[6])c-=t[7];
        return std::max(c,t[8])*t[0]*std::max(ny,.1);
    }
    double traction(double pitch) const {
        const double ny=std::cos(pitch);
        return (ny>=t[14]?t[16]:ny<=t[13]?t[15]:
            t[15]+(ny-t[13])/(t[14]-t[13])*(t[16]-t[15]))*t[12];
    }
    double engine(double v,double throttle,double pitch) const {
        if(!throttle)return 0.;
        double pw=power*t[9]*ratio;if(throttle<0.)pw*=t[10];
        return std::min(pw/std::max(std::abs(v),t[11]),
            traction(pitch)*mass*t[0]*std::max(std::cos(pitch),.1))*throttle;
    }
    double rolling(int index,double steering) const {
        return friction*t[1]*terrain[index]*(steering?
            1.+(t[17]-1.)*std::min(1.,std::abs(steering)):1.);
    }
    double cap(double v) const {
        const double limit=(v>=0.?forward:reverse)*t[23];return clamp(v,-limit,limit);
    }
    double longitudinal(double v,double throttle,double steering,double pitch,double dt,
                        bool airborne,int index,bool hand,bool service) const {
        if(airborne)return v;
        const double gravity=t[0]*std::sin(pitch),hold=grip(pitch);
        if(service&&throttle*v<0.&&!hand){
            const double decel=std::min(brake,hold),nv=v+(gravity-(v>0.?decel:-decel))*dt;
            return v*nv<=0.?0.:cap(nv);
        }
        if(hand){
            if(std::abs(v)<.05){
                if(std::abs(gravity)<=hold)return 0.;
                return cap(v+(gravity-(gravity>0.?hold:-hold))*dt);
            }
            const double nv=v+(gravity-(v>0.?hold:-hold))*dt;
            return (v>0.)!=(nv>0.)?0.:cap(nv);
        }
        const double rr=rolling(index,steering);double acceleration=0.,force=0.;
        if(throttle!=0.){
            force=engine(v,throttle,pitch)*(1.-.25*std::min(1.,std::abs(steering)))/mass;
            const double ny=std::cos(pitch);
            const bool cant=throttle*gravity<0.&&traction(pitch)*t[0]*std::max(ny,.1)<std::abs(gravity)+rr;
            if(cant)force=0.;
            acceleration=force+gravity-rr*clamp(v/.08,-1.,1.);
            if(cant&&std::abs(v)>.05)acceleration+=(v<0.?1.:-1.)*t[19]*t[0]*std::max(ny,.1);
        }else if(std::abs(v)<.02){
            const double perch=t[18]*t[0]*std::max(std::cos(pitch),.1);
            if(std::abs(gravity)<=perch)return 0.;
            acceleration=gravity-(gravity>0.?perch:-perch);
        }else{
            const double downhill=std::max(0.,std::tan(pitch)*(v>0.?1.:-1.)),fade_start=.8*t[18];
            const double fade=clamp((downhill-fade_start)/(t[18]-fade_start),0.,1.);
            const double resist=rr+(1.-fade)*std::max(0.,t[22]*std::min(brake,hold)-rr);
            acceleration=gravity-(v>0.?resist:-resist);
        }
        const double grade=v>0.?-pitch:pitch;
        if(std::abs(v)>.5&&grade>0.&&std::tan(grade)>t[20])
            acceleration-=(v>0.?1.:-1.)*t[21]*(std::tan(grade)-t[20])*t[0];
        double nv=v+acceleration*dt;
        if(throttle==0.&&std::abs(gravity)<=hold&&v!=0.&&(v>0.)!=(nv>0.))nv=0.;
        if(throttle!=0.&&force*throttle>0.){
            const double sign=throttle>0.?1.:-1.,limit=throttle>0.?forward:reverse,passive=v+(acceleration-force)*dt;
            nv=passive+sign*std::min(std::abs(force)*dt,std::max(0.,limit-sign*passive));
        }
        return cap(nv);
    }
    double traverse(double omega,double turn,double v,double dt,int index,double intent) const {
        const double limit=rotation/(1.+std::abs(v)/std::max(forward,.1)*t[25])*terrain[0]/terrain[index];
        const double target=turn*(intent<0.?-1.:1.)*limit,diff=target-omega,ramp=limit/t[24];
        if(std::abs(diff)<ramp*dt)omega=target;else omega+=ramp*dt*(diff>0.?1.:-1.);
        return turn==0.&&std::abs(omega)<.01?0.:omega;
    }
};
}
PyObject *WOT_CDECL release_drive(PyObject *,PyObject *args) {
    NATIVE_PROFILE_ENTRY(release_drive);
    try {
        require_sequence(args,4,true);PyObject **a=items(args);
        const int op=index_value(a[0]);if(op<0||op>3||!plain_dict(a[1]))throw Unsupported();
        require_sequence(a[2],op==0?9:op==2?5:6,true);require_sequence(a[3],26,true);
        release_drive_law::Law law;
        for(int i=0;i<26;++i)law.t[i]=finite_number(items(a[3])[i]);
        law.mass=finite_number(field(a[1],MASS));law.power=finite_number(field(a[1],PH_POWER));
        PyObject *ratio=field(a[1],PH_POWER_RATIO);law.ratio=absent(ratio)?1.:finite_number(ratio);
        law.forward=finite_number(field(a[1],PH_FORWARD));law.reverse=finite_number(field(a[1],PH_REVERSE));
        law.friction=finite_number(field(a[1],PH_FRICTION));law.brake=finite_number(field(a[1],PH_BRAKE));
        law.rotation=finite_number(field(a[1],PH_ROTATION));PyObject *terrain=field(a[1],PH_TERRAIN);
        require_sequence(terrain,3,true);for(int i=0;i<3;++i)law.terrain[i]=finite_number(items(terrain)[i]);
        if(law.mass<=0.||law.t[11]<=0.||law.t[14]<=law.t[13]||law.t[18]<=0.||law.t[24]<=0.||
            law.terrain[0]<=0.||law.terrain[1]<=0.||law.terrain[2]<=0.)throw Unsupported();
        double v[9]={};for(Py_ssize_t i=0;i<size(a[2]);++i)v[i]=finite_number(items(a[2])[i]);
        int index=op==0?index_value(items(a[2])[6]):op==1?index_value(items(a[2])[4]):0;
        if(index<0){index+=3;}if(index<0||index>=3)throw Unsupported();
        if(op==3){
            const auto r=profile.run([&](){
                if(v[2]==0.||v[3]<=0.)return std::array<double,2>{{0.,0.}};
                const double omega=law.traverse(0.,v[2],v[1],std::max(v[3],law.t[24]),0,v[4]);
                return std::array<double,2>{{omega,std::abs(law.engine(std::abs(v[1])+std::abs(omega)*v[0],v[2],v[5]))*
                    (1.-.75*std::min(1.,std::abs(v[4])))*v[0]}};
            });OwnedTuple out(2);out.set(0,float_new(r[0]));out.set(1,float_new(r[1]));return out.release();
        }
        const double r=profile.run([&](){
            if(op==0)return law.longitudinal(v[0],v[1],v[2],v[3],v[4],v[5]!=0.,index,v[7]!=0.,v[8]!=0.);
            if(op==1)return law.traverse(v[0],v[1],v[2],v[3],index,v[5]);
            double current=v[0],distance=0.;if(std::abs(current)<=v[3])return 0.;
            for(int i=0;i<4096;++i){
                const double next=law.longitudinal(current,0.,v[2]!=0.,v[1],v[4],false,0,false,false);
                if(!std::isfinite(next))return std::numeric_limits<double>::infinity();
                if(std::abs(next)<=v[3])return distance+std::abs(next)*v[4];
                if(std::abs(next)>=std::abs(current))return std::numeric_limits<double>::infinity();
                distance+=std::abs(next)*v[4];current=next;
            }return std::numeric_limits<double>::infinity();
        });return float_new(r);
    }catch(const PythonAllocationFailed &){profile.fail();return 0;}
     catch(...){profile.fail();return fallback();}
}
