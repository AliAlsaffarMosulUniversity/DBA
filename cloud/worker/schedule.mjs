const invalid=message=>{const error=new Error(message);error.status=422;throw error;};
export function conflicts(rows){
  const issues=[];
  for(let i=0;i<rows.length;i++)for(let j=i+1;j<rows.length;j++){
    const a=rows[i],b=rows[j];if(a.date!==b.date||a.start>=b.end||b.start>=a.end)continue;
    const staff=a.staff.filter(id=>b.staff.includes(id));
    if(staff.length||a.group===b.group||a.room===b.room)issues.push({first:i+1,second:j+1,reason:[staff.length?'تدريسي أو مراقب':'',a.group===b.group?'شعبة':'',a.room===b.room?'قاعة':''].filter(Boolean).join(' / ')});
  }return issues;
}
export function validateRows(rows,profiles){
  if(!Array.isArray(rows)||!rows.length||rows.length>100)invalid('أدخل من 1 إلى 100 جلسة');
  const ids=new Set(profiles.map(p=>p.id));
  const clean=rows.map(r=>{
    if(!r||typeof r.title!=='string'||!r.title.trim()||r.title.length>150||typeof r.group!=='string'||!r.group.trim()||r.group.length>100||typeof r.room!=='string'||!r.room.trim()||r.room.length>100)invalid('المقرر والشعبة والقاعة مطلوبة');
    if(!/^\d{4}-\d{2}-\d{2}$/.test(r.date)||!Number.isFinite(Date.parse(r.date))||new Date(r.date).toISOString().slice(0,10)!==r.date)invalid('تاريخ غير صالح');
    if(!/^([01]\d|2[0-3]):[0-5]\d$/.test(r.start)||!/^([01]\d|2[0-3]):[0-5]\d$/.test(r.end)||r.start>=r.end)invalid('وقت الجلسة غير صالح');
    if(!Array.isArray(r.staff)||!r.staff.length||r.staff.length>10||new Set(r.staff).size!==r.staff.length||r.staff.some(id=>!ids.has(id)))invalid('اختر تدريسيًا أو مراقبًا مسجلًا');
    return {title:r.title.trim(),date:r.date,start:r.start,end:r.end,group:r.group.trim(),room:r.room.trim(),staff:r.staff};
  });return clean;
}
