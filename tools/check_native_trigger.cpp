// C++17 host contract checks for the production physical-trigger owner.
// No Python, BigWorld, Windows ABI, client assets or test-only physics model.
// Build with native/offline_simulation_weapons.cpp and -I native.
#include "offline_simulation_weapons.h"
#include <cmath>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace w = offline_simulation::weapons;
using offline_simulation::ActorKey;
using offline_simulation::ActorKind;

namespace {
unsigned checks=0;

void check(bool value,const char *message) {
    ++checks;
    if(!value) throw std::runtime_error(message);
}

bool near(double left,double right) {return std::abs(left-right)<=1.e-12;}

std::string fingerprint(const w::ActorState &state) {
    const auto &g=state.gun;const auto &a=state.ammo;const auto &b=state.burst;
    std::ostringstream result;result<<std::setprecision(17);
    result<<state.fire_seq<<' '<<g.clip<<' '<<g.burst_remaining<<' '
          <<g.elapsed<<' '<<g.reload_duration<<' '<<g.reload_factor<<' '<<g.intra<<' '
          <<g.current_dispersion_factor<<' '<<g.aiming_start_factor<<' '
          <<g.aiming_elapsed<<' '<<g.dispersion<<' '<<g.motion_dispersion_squared<<' '
          <<a.loaded<<' '<<a.next<<' '<<a.reload_pending<<' '<<a.plan_pending<<' '
          <<b.active<<' '<<b.group_seq<<' '<<b.count<<' '<<b.next_index<<' '
          <<b.interval<<' '<<b.time_left<<' '<<b.shell<<' '
          <<static_cast<int>(b.terminal_reason)<<' ';
    for(int value:a.categories) result<<value<<' ';
    result<<'|';for(int value:a.remaining) result<<value<<' ';
    return result.str();
}

w::GunConfig config(int clip=6,int burst=3) {
    w::GunConfig result;
    result.fully_aimed_dispersion=.035;result.after_shot=2.1;
    result.after_shot_in_burst=.6;result.turret_dispersion_factor=.08;
    result.aiming_time=2.2;result.movement_dispersion_factor=.12;
    result.rotation_dispersion_factor=.15;result.reload_full=.6;
    result.reload_intra=.17;result.clip_size=clip;result.shell_count=3;
    result.burst_count=burst;result.burst_interval=burst>1?.1:0.;
    return result;
}

w::AmmoState ammo(int rounds=12) {
    w::AmmoState result;result.categories={0,1,2};result.remaining={rounds,9,0};
    return result;
}

w::LaunchRecord launch(ActorKey actor,const w::BurstEdge &edge) {
    w::LaunchRecord result;result.actor=actor;result.edge=edge;
    result.launch_time_us=14400000000LL+edge.shot_seq*100000;
    result.pose.position={{1.,2.,3.}};result.pose.yaw=.1;
    result.pose.pitch=-.03;result.pose.roll=.02;
    result.yaw=.15+edge.index*.01;result.pitch=.02;
    result.has_origin=true;result.origin={{1.1,2.2,3.3}};
    result.class_tag="mediumTank";
    return result;
}

std::vector<w::BurstEdge> advance(w::Store &store,ActorKey key,double dt) {
    w::AimInput input;input.dt=dt;
    return store.after_motion(key,input,0.,0.,0.,1.,1.,false);
}

void rejects(w::Store &store,ActorKey key,const w::LaunchRecord &record,
             const char *message) {
    const auto before=fingerprint(store.at(key));
    const auto pending=store.pending().size();
    check(!store.commit(key,record,1.),message);
    check(before==fingerprint(store.at(key)),"rejection changed weapon state");
    check(pending==store.pending().size(),"rejection changed projectile outbox");
}

void clock_contract() {
    w::BurstState clock;
    check(clock.start(17,3,.1,2),"trigger did not arm");
    auto first=clock.advance(0.);
    check(first.size()==1 && first[0].index==0,"first edge must be due immediately");
    check(clock.active && clock.next_index==0,"exposure spent the first edge");
    check(clock.advance(0.).size()==1,"uncommitted edge was lost on repeated exposure");
    auto invalid=first[0];invalid.final_round=true;
    check(!clock.commit(invalid),"nonfinal round accepted as final");
    invalid=first[0];++invalid.shell;
    check(!clock.commit(invalid),"trigger changed loaded ammunition");
    invalid=first[0];++invalid.group_seq;
    check(!clock.commit(invalid),"trigger accepted another group");
    check(clock.commit(first[0]),"first physical edge did not commit");
    check(clock.active && clock.next_index==1 && near(clock.time_left,.1),
          "first commit did not advance exactly one interval");
    check(!clock.commit(first[0]),"duplicate physical edge committed twice");
    check(!clock.abort(),"a committed trigger was aborted");
    invalid=first[0];++invalid.shot_seq;++invalid.index;
    check(!clock.commit(invalid),"second round fired before its cadence");
    check(clock.advance(.04).empty(),"early clock step emitted a round");
    auto due=clock.advance(.21);
    check(due.size()==2,"long step dropped a due physical round");
    check(clock.active && clock.next_index==1 && near(clock.time_left,-.15),
          "due scheduling altered committed state");
    check(near(due[0].due_offset,.06) && near(due[1].due_offset,.16),
          "due offsets lost their subframe times");
    check(!clock.commit(due[1]),"last edge overtook an earlier due edge");
    check(clock.commit(due[0]) && clock.commit(due[1]),"due edges did not drain");
    check(!clock.active && clock.next_index==3 && clock.time_left==0.,
          "last physical commit did not complete the trigger");
    check(!clock.commit(due[1]) && !clock.abort(),"completion allowed physical rollback");
    clock.validate(19);
    check(clock.start(20,3,.1,2),"next trigger could not arm");
    check(clock.abort() && clock.count==0 && clock.group_seq==0,
          "uncommitted trigger could not be withdrawn");
    check(clock.start(20,3,.1,2),"trigger could not rearm after abort");
    check(clock.commit(clock.advance(0.).front()),"new first edge failed");
    for(int bad:{0,10,-1}) {
        bool rejected=false;
        try {clock.terminate(static_cast<w::TerminationReason>(bad));}
        catch(const std::invalid_argument &) {rejected=true;}
        check(rejected && clock.active && clock.next_index==1,
              "invalid termination reason withdrew a committed trigger");
    }
    check(clock.terminate(w::TerminationReason::ActorDestroyed),
          "physical actor destruction could not terminate a trigger");
    check(!clock.active && clock.next_index==1 && clock.count==3,
          "physical termination discarded committed identity");
    clock.validate(20);
    check(clock.terminal_reason==w::TerminationReason::ActorDestroyed,
          "physical termination reason was lost");
}

void atomic_store_contract(ActorKind kind) {
    const ActorKey key{kind,41};w::Store store;store.install(key,config(),ammo(),0,1.);
    const auto installed=fingerprint(store.at(key));
    check(!store.begin(key,3,.1,1.) && installed==fingerprint(store.at(key)),
          "failed arm changed reload or trigger state");
    store.prepare(key,1.,1.,0);
    const auto ready=fingerprint(store.at(key));
    check(store.begin(key,3,.1,1.),"ready weapon did not arm");
    auto due=advance(store,key,0.);
    check(due.size()==1 && store.at(key).burst.next_index==0,
          "store exposure consumed an unlaunched round");
    const auto armed=fingerprint(store.at(key));
    check(!store.begin(key,3,.1,1.) && armed==fingerprint(store.at(key)),
          "repeated begin cancelled an already armed trigger");
    check(store.abort(key),"store could not abort before first physical commit");
    check(ready==fingerprint(store.at(key)),"uncommitted abort spent ammo or reload readiness");
    check(store.begin(key,3,.1,1.),"aborted store could not rearm");
    due=advance(store,key,0.);
    auto first=launch(key,due.front());
    auto invalid=first;invalid.edge.count=2;
    rejects(store,key,invalid,"wrong trigger count was accepted");
    invalid=first;invalid.edge.shell=1;
    rejects(store,key,invalid,"wrong physical shell was accepted");
    invalid=first;invalid.actor.id=42;
    rejects(store,key,invalid,"different actor's projectile was accepted");
    check(store.commit(key,first,1.),"first physical launch was rejected");
    const auto &after=store.at(key);
    check(after.fire_seq==1 && after.burst.next_index==1 && after.gun.clip==5 &&
          after.gun.burst_remaining==2 && after.ammo.remaining[0]==11,
          "atomic first commit did not update all physical owners");
    check(store.pending().size()==1 && store.pending().front().shells_before==21,
          "physical outbox did not freeze pre-shot stock");
    check(near(after.gun.current_dispersion_factor,std::sqrt(1.+.6*.6)),
          "nonfinal shell did not select afterShotInBurst");
    rejects(store,key,first,"duplicate first launch spent ammunition again");
    const auto committed=fingerprint(store.at(key));
    check(!store.abort(key) && committed==fingerprint(store.at(key)),
          "Store.abort rolled back a committed trigger");
    store.prepare(key,100.,2.,1);
    check(committed==fingerprint(store.at(key)),
          "active trigger allowed reload or tactical ammunition retargeting");
    invalid=first;++invalid.edge.index;++invalid.edge.shot_seq;
    rejects(store,key,invalid,"future physical launch ignored cadence");
    due=advance(store,key,.35);
    check(due.size()==2 && store.at(key).burst.next_index==1,
          "slow callback speculatively committed tail rounds");
    rejects(store,key,launch(key,due.back()),"tail round bypassed committed frontier");
    for(const auto &edge:due) check(store.commit(key,launch(key,edge),1.),"tail physical commit failed");
    const auto &complete=store.at(key);
    check(!complete.burst.active && complete.burst.next_index==3 &&
          complete.fire_seq==3 && complete.gun.clip==3 &&
          complete.gun.burst_remaining==0 && complete.ammo.remaining[0]==9,
          "trigger completion lost gun/ammo/frontier atomicity");
    check(complete.gun.intra && complete.gun.elapsed==0. &&
          complete.gun.reload_duration==config().reload_intra,
          "next-trigger reload did not begin at the final physical shell");
    check(near(complete.gun.current_dispersion_factor,std::sqrt(1.+2.1*2.1)),
          "last shell did not select afterShot");
    check(store.pending().size()==3 && store.pending()[1].yaw!=store.pending()[2].yaw,
          "per-shell launch rays were merged into one trigger ray");
    complete.burst.validate(3);
    auto frozen=store.pending().front();
    check(!store.enqueue(frozen),"identical frozen launch was duplicated");
    auto conflict=frozen;conflict.yaw+=.01;
    bool rejected=false;
    try {store.enqueue(conflict);} catch(const std::invalid_argument &) {rejected=true;}
    check(rejected && store.pending().front()==frozen,"frozen launch identity was overwritten");
    check(!store.ack(key,2) && !store.remove(key),"outbox owner/order fence was bypassed");
    for(int index=1;index<=3;++index) check(store.ack(key,index),"ordered physical launch ack failed");
    check(store.remove(key),"settled physical owner could not be removed");
}

void precommit_physical_termination() {
    for(const auto kind:{ActorKind::Human,ActorKind::Bot}) {
        for(int value=1;value<=9;++value) {
            const auto reason=static_cast<w::TerminationReason>(value);
            const ActorKey key{kind,89};w::Store store;
            store.install(key,config(),ammo(),0,1.);store.prepare(key,1.,1.,0);
            auto expected=store.at(key);
            check(store.begin(key,3,.1,1.),"precommit termination fixture did not arm");
            check(advance(store,key,0.).size()==1,"precommit trigger did not expose its first edge");
            check(store.terminate(key,reason),"explicit precommit physical failure was rejected");
            expected.burst.terminal_reason=reason;
            check(fingerprint(store.at(key))==fingerprint(expected),
                  "precommit physical termination spent ammo, cooldown or committed history");
            check(store.at(key).gun.ready(1.) && store.at(key).ammo.can_fire() &&
                  store.pending().empty(),"unlaunched trigger left a cooldown or phantom launch");
            store.at(key).burst.validate(0);
            check(store.begin(key,3,.1,1.),"precommit physical failure prevented the next real trigger");
        }
    }
}

void physical_failure_and_partial_clip() {
    const ActorKey key{ActorKind::Bot,91};w::Store store;
    store.install(key,config(6,3),ammo(2),0,1.);store.prepare(key,1.,1.,0);
    check(store.begin(key,3,.1,1.),"partial-stock trigger did not arm");
    auto due=advance(store,key,0.);
    check(due.front().count==2,"trigger did not clamp to physical carried stock");
    check(store.commit(key,launch(key,due.front()),1.),"partial-stock first shell failed");
    const auto before=fingerprint(store.at(key));
    bool rejected=false;
    try {store.terminate(key,w::TerminationReason::None);}
    catch(const std::invalid_argument &) {rejected=true;}
    check(rejected && before==fingerprint(store.at(key)),"missing lifecycle reason terminated trigger");
    check(store.terminate(key,w::TerminationReason::GunUnavailable),"physical gun failure was rejected");
    check(store.at(key).fire_seq==1 && store.at(key).ammo.remaining[0]==1 &&
          store.at(key).burst.next_index==1 && !store.at(key).burst.active &&
          store.pending().size()==1,"physical termination erased or invented a shell");
    store.at(key).burst.validate(1);
    store.prepare(key,1.,1.,0);
    check(store.begin(key,3,.1,1.),"one remaining physical round could not arm");
    due=advance(store,key,0.);
    check(due.size()==1 && due.front().count==1 && due.front().final_round,
          "partial last trigger was not one real final round");
    check(store.commit(key,launch(key,due.front()),1.),"partial last shell did not commit");
    const auto &last=store.at(key);
    check(last.ammo.remaining[0]==0 && last.ammo.next==1 && last.gun.clip==0 &&
          !last.gun.intra && last.gun.reload_duration==config().reload_full,
          "exhausted shell did not use a full physical reload boundary");
    store.prepare(key,1.,1.,1);
    check(store.at(key).ammo.loaded==1 && store.at(key).gun.clip==6,
          "next ammunition was not installed at full reload completion");
}

void restored_trigger_contract() {
    const ActorKey key{ActorKind::Bot,117};w::Store original;
    original.install(key,config(),ammo(),0,1.);original.prepare(key,1.,1.,0);
    check(original.begin(key,3,.1,1.),"restore fixture did not arm");
    const auto first=advance(original,key,0.).front();
    check(original.commit(key,launch(key,first),1.),"restore fixture first commit failed");
    const auto active=original.at(key);
    check(original.terminate(key,w::TerminationReason::GunUnavailable),
          "restore fixture physical termination failed");
    const auto terminated=original.at(key);
    w::Store restored;restored.install(key,config(),terminated.ammo,terminated.fire_seq,1.);
    restored.at(key).gun=terminated.gun;
    // Simulate a legacy donor that reconstructed remaining count without
    // checking whether the published group was still physically active.
    restored.at(key).gun.burst_remaining=terminated.burst.count-terminated.burst.next_index;
    restored.restore_trigger(key,terminated.burst,terminated.fire_seq);
    check(restored.at(key).gun.burst_remaining==0 && !restored.at(key).burst.active,
          "terminated checkpoint resurrected the gun's unlaunched tail");
    check(fingerprint(restored.at(key))==fingerprint(terminated),
          "terminated restore changed ammo, clip, reload or committed history");
    const int stock=restored.at(key).ammo.remaining[0];
    check(advance(restored,key,1.).empty() && restored.at(key).ammo.remaining[0]==stock,
          "inactive restored history emitted a physical tail shell");
    restored.prepare(key,1.,1.,0);
    check(restored.begin(key,3,.1,1.) && restored.at(key).burst.group_seq==2,
          "stale restored tail jammed the next real trigger");

    w::Store continuing;continuing.install(key,config(),active.ammo,active.fire_seq,1.);
    continuing.at(key).gun=active.gun;continuing.at(key).gun.burst_remaining=0;
    continuing.restore_trigger(key,active.burst,active.fire_seq);
    check(continuing.at(key).gun.burst_remaining==2 && continuing.at(key).burst.active,
          "valid active checkpoint did not restore its physical tail");
    check(fingerprint(continuing.at(key))==fingerprint(active),
          "active restore changed physical committed state");
    auto malformed=active.burst;malformed.shell=1;
    const auto before=fingerprint(continuing.at(key));
    bool rejected=false;
    try {continuing.restore_trigger(key,malformed,active.fire_seq);}
    catch(const std::invalid_argument &) {rejected=true;}
    check(rejected && fingerprint(continuing.at(key))==before,
          "mismatched restored ammunition changed native state");
    const auto due=advance(continuing,key,.3);
    check(due.size()==2,"restored active trigger lost a physical tail shell");
    for(const auto &edge:due)
        check(continuing.commit(key,launch(key,edge),1.),"restored active tail failed to commit");
    check(continuing.at(key).fire_seq==3 && continuing.at(key).gun.burst_remaining==0 &&
          continuing.pending().size()==2,"restored physical tail did not complete exactly once");
}
}

int main() {
    try {
        clock_contract();atomic_store_contract(ActorKind::Human);
        atomic_store_contract(ActorKind::Bot);precommit_physical_termination();
        physical_failure_and_partial_clip();
        restored_trigger_contract();
        std::cout<<"{\"result\":\"pass\",\"host_contract_checks\":"<<checks
                 <<",\"coverage\":[\"nonconsuming_due_edges\",\"physical_commit_frontier\","
                 <<"\"subframe_cadence\",\"precommit_abort\",\"precommit_physical_termination\","
                 <<"\"reason_gated_termination\","
                 <<"\"human_bot_store_parity\",\"atomic_ammo_gun_trigger\","
                 <<"\"per_shell_immutable_launch\",\"partial_clip\",\"reload_boundary\","
                 <<"\"terminated_trigger_restore\",\"active_trigger_restore\"]}\n";
        return 0;
    } catch(const std::exception &error) {
        std::cerr<<"native trigger contract failed: "<<error.what()<<'\n';return 1;
    }
}
