from app.scheduler import Request,solve

def test_department_sized_45_teachers_30_groups_21_rooms():
    req=Request(kind='weekly',days=5,periods=12,time_limit=15,
      rooms=[{'id':f'R{i}','capacity':60} for i in range(21)],
      lessons=[{'id':str(i),'teacher':i%45+2,'group':f'G{i//12}','title':'Course','shift':'morning' if (i//12)%2==0 else 'evening','size':35,'duration':1} for i in range(360)])
    result=solve(req)
    assert result['status'] in ('FEASIBLE','OPTIMAL'),result
    assert len(result['entries'])==360
    occupied=set()
    for e in result['entries']:
        for key in [('teacher',e['teacher']),('group',e['group']),('room',e['room'])]:
            slot=(key,e['day'],e['period']);assert slot not in occupied;occupied.add(slot)
