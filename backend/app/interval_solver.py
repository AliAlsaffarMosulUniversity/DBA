"""Interval CP-SAT model: scales with lessons × rooms, not lessons × time × rooms."""
from ortools.sat.python import cp_model

def solve(req):
    failure=lambda message:{'status':'INFEASIBLE','message':message,'entries':[]}
    if req.kind=='weekly':
        for teacher,limit in req.teacher_limits.items():
            if sum(l.duration for l in req.lessons if l.teacher==teacher)>limit:return failure(f'تجاوز النصاب المسموح للتدريسي {teacher}')
    model=cp_model.CpModel();resources={};starts=[];rooms=[];monitor_choices=[];day_vars=[];penalties=[];domains=[]
    pairs={frozenset(p) for p in req.conflicts}
    def reserve(resource,interval):resources.setdefault(resource,[]).append(interval)
    for room in req.rooms:
        for slot in set(room.blocked):
            if 0<=slot<req.days*req.periods:reserve(('room',room.id),model.new_fixed_size_interval_var(slot,1,f'room_block_{room.id}_{slot}'))
    if req.kind=='exam':
        for m in req.monitor_pool:
            for slot in set(m.blocked):
                if 0<=slot<req.days*req.periods:reserve(('teacher',m.teacher),model.new_fixed_size_interval_var(slot,1,f'monitor_block_{m.teacher}_{slot}'))
    for i,l in enumerate(req.lessons):
        allowed=[]
        for d in range(req.days):
            for p in range(req.periods-l.duration+1):
                if req.timeline:
                    slots=req.timeline[p:p+l.duration]
                    if any(a.end!=b.start for a,b in zip(slots,slots[1:])):continue
                    if req.kind=='weekly' and any(s.shift!=l.shift for s in slots):continue
                elif req.kind=='weekly' and not (p+l.duration<=req.periods//2 if l.shift=='morning' else p>=req.periods//2):continue
                start=d*req.periods+p
                if not set(range(start,start+l.duration))&set(l.blocked):allowed.append(start)
        feasible=[r for r in req.rooms if r.capacity>=l.size and (not l.room_type or r.room_type==l.room_type) and set(l.equipment)<=set(r.equipment)]
        if not allowed or not feasible:return failure('لا توجد فترة وقاعة مناسبة: '+l.id)
        domains.append(allowed)
        start=model.new_int_var_from_domain(cp_model.Domain.from_values(allowed),f'start_{i}');starts.append(start)
        interval=model.new_fixed_size_interval_var(start,l.duration,f'lesson_{i}')
        reserve(('teacher',l.teacher),interval);reserve(('group',l.group),interval)
        for pair in pairs:
            if l.group in pair:reserve(('shared',tuple(sorted(pair))),interval)
        choices=[]
        for room in feasible:
            selected=model.new_bool_var(f'room_{i}_{room.id}');choices.append((room.id,selected))
            reserve(('room',room.id),model.new_optional_fixed_size_interval_var(start,l.duration,selected,f'room_interval_{i}_{room.id}'))
        model.add_exactly_one([v for _,v in choices]);rooms.append(choices)
        day=model.new_int_var(0,req.days-1,f'day_{i}');model.add_division_equality(day,start,req.periods)
        if req.dates:
            offsets=[(d-req.dates[0]).days for d in req.dates]
            actual=model.new_int_var(0,max(offsets),f'calendar_{i}');model.add_element(day,offsets,actual);day_vars.append(actual)
        else:day_vars.append(day)
        monitors=[]
        if req.kind=='exam' and l.monitors:
            for m in req.monitor_pool:
                if m.teacher==l.teacher:continue
                selected=model.new_bool_var(f'monitor_{i}_{m.teacher}');monitors.append((m.teacher,selected))
                reserve(('teacher',m.teacher),model.new_optional_fixed_size_interval_var(start,l.duration,selected,f'monitor_interval_{i}_{m.teacher}'))
            model.add(sum(v for _,v in monitors)==l.monitors)
        monitor_choices.append(monitors)
        if l.preferred:
            penalty=model.new_int_var(0,1,f'preference_{i}')
            model.add_allowed_assignments([start,penalty],[(v,int(v not in l.preferred)) for v in allowed]);penalties.append(penalty)
    if req.kind=='exam':
        for m in req.monitor_pool:model.add(sum(v for choices in monitor_choices for t,v in choices if t==m.teacher)<=m.max_sessions)
        maximum=(req.dates[-1]-req.dates[0]).days if req.dates else req.days-1
        for i,a in enumerate(req.lessons):
            for j,b in enumerate(req.lessons[:i]):
                if a.group==b.group or frozenset((a.group,b.group)) in pairs:
                    diff=model.new_int_var(0,maximum,f'gap_{i}_{j}');model.add_abs_equality(diff,day_vars[i]-day_vars[j]);model.add(diff>=req.exam_gap_days+1)
    for intervals in resources.values():model.add_no_overlap(intervals)
    if penalties:model.minimize(sum(penalties))
    # A greedy assignment is only a search hint. CP-SAT still verifies every
    # constraint, and a failed greedy attempt never means the plan is infeasible.
    if req.kind=='weekly':
        taken={};hints=[];room_blocks={r.id:set(r.blocked) for r in req.rooms}
        for i,l in enumerate(req.lessons):
            shared=[('teacher',l.teacher),('group',l.group)]+[('shared',tuple(sorted(p))) for p in pairs if l.group in p]
            found=None
            for start in sorted(domains[i],key=lambda s:(bool(l.preferred) and s not in l.preferred,s)):
                occupied=set(range(start,start+l.duration))
                if any(occupied&taken.get(key,set()) for key in shared):continue
                for room,var in rooms[i]:
                    if not occupied&(room_blocks[room]|taken.get(('room',room),set())):
                        found=(start,room,occupied);break
                if found:break
            if not found:break
            start,room,occupied=found;hints.append((i,start,room))
            for key in shared+[('room',room)]:taken.setdefault(key,set()).update(occupied)
        if len(hints)==len(req.lessons):
            for i,start,room in hints:
                model.add_hint(starts[i],start)
                for r,var in rooms[i]:model.add_hint(var,int(r==room))
    solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=req.time_limit;solver.parameters.num_search_workers=8;solver.parameters.max_presolve_iterations=1
    if req.kind=='weekly' and len(req.lessons)>=100 and len(hints)==len(req.lessons):
        # Large symmetric room sets spend most time in presolve. A complete
        # feasible hint lets search validate the actual model directly.
        solver.parameters.cp_model_presolve=False;solver.parameters.symmetry_level=0
    status=solver.solve(model)
    if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):return {'status':solver.status_name(status),'message':'القيود متعذرة' if status==cp_model.INFEASIBLE else 'انتهت مهلة البحث دون حل مثبت؛ غيّر القيود أو حجم الخطة','entries':[]}
    entries=[]
    for i,l in enumerate(req.lessons):
        value=solver.value(starts[i]);d,p=divmod(value,req.periods)
        entries.append({**l.model_dump(),'day':d,'period':p,'room':next(r for r,v in rooms[i] if solver.value(v)),
          'date':req.dates[d].isoformat() if req.dates else None,'start':req.timeline[p].start if req.timeline else None,'end':req.timeline[p+l.duration-1].end if req.timeline else None,
          'invigilators':[t for t,v in monitor_choices[i] if solver.value(v)]})
    return {'status':solver.status_name(status),'preference_penalty':solver.objective_value if penalties else 0,'entries':sorted(entries,key=lambda e:(e['day'],e['period'],e['room']))}
