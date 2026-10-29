document.addEventListener('DOMContentLoaded',()=>{
 const key='tracker-theme';
 const saved=localStorage.getItem(key);
 if(saved==='dark') document.body.classList.add('dark');
 const themeBtn=document.getElementById('themeToggle');
 const sun='<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"></path></svg>';
 const moon='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5 8.5 8.5 0 1 0 20.5 14.2Z"></path></svg>';
 const syncTheme=()=>{
   if(!themeBtn) return;
   const dark=document.body.classList.contains('dark');
   themeBtn.innerHTML=dark?sun:moon;
   themeBtn.setAttribute('aria-label',dark?'Светлая тема':'Темная тема');
   themeBtn.title=dark?'Светлая тема':'Темная тема';
 };
 syncTheme();
 if(themeBtn){themeBtn.addEventListener('click',()=>{document.body.classList.toggle('dark');localStorage.setItem(key,document.body.classList.contains('dark')?'dark':'light');syncTheme();});}
 // Меню пользователя: открывается поверх страницы и не вызывает прокрутку страницы.
 const userWrap=document.querySelector('.user-menu-wrap');
 const userTrigger=userWrap?.querySelector('.user-menu-trigger');
 const userMenu=userWrap?.querySelector('.user-menu');
 const closeUserMenu=()=>{
   if(!userWrap) return;
   userWrap.classList.remove('open');
   document.body.classList.remove('user-menu-open');
 };
 if(userWrap && userTrigger && userMenu){
   userTrigger.setAttribute('type','button');
   userTrigger.setAttribute('aria-expanded','false');
   userTrigger.addEventListener('click',e=>{
     e.stopPropagation();
     const open=!userWrap.classList.contains('open');
     userWrap.classList.toggle('open',open);
     userTrigger.setAttribute('aria-expanded',open?'true':'false');
     document.body.classList.toggle('user-menu-open',open);
   });
   userMenu.addEventListener('click',e=>e.stopPropagation());
   document.addEventListener('click',closeUserMenu);
   document.addEventListener('keydown',e=>{if(e.key==='Escape')closeUserMenu();});
 }

 const clock=document.getElementById('appClock');
 const tick=()=>{if(!clock)return; const d=new Date(); const days=['воскресенье','понедельник','вторник','среда','четверг','пятница','суббота']; clock.textContent=`${days[d.getDay()]}, ${d.toLocaleDateString('ru-RU')} ${d.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}`;};
 tick(); setInterval(tick,1000);
 document.querySelectorAll('.alert[data-autoclose="true"]').forEach(a=>setTimeout(()=>{if(window.bootstrap){bootstrap.Alert.getOrCreateInstance(a).close();}else{a.remove();}},5000));

 // QR-виджет подключения
 const qrw=document.getElementById('qrWidget');
 if(qrw){const t=qrw.querySelector('.qr-toggle');t.addEventListener('click',e=>{e.stopPropagation();qrw.classList.toggle('open');});document.addEventListener('click',e=>{if(!qrw.contains(e.target))qrw.classList.remove('open');});
   const img=qrw.querySelector('img');if(img){img.addEventListener('error',()=>{img.style.display='none';});}}
 // Сортировка по имени: <th data-sort="N"> - N индекс колонки; строки в первом tbody
 window.trackerRenumber=function(table){let n=0;table.querySelectorAll('tbody tr').forEach(r=>{const c=r.querySelector('.row-num');if(c&&r.style.display!=='none'){c.textContent=++n;}});};
 document.querySelectorAll('th[data-sort]').forEach(th=>{
   const arrow=document.createElement('span');arrow.className='sort-arrow';th.appendChild(arrow);
   th.addEventListener('click',()=>{
     const table=th.closest('table'),body=table.tBodies[0],idx=+th.dataset.sort,dir=th.dataset.dir==='asc'?'desc':'asc';
     table.querySelectorAll('th[data-sort]').forEach(x=>{x.dataset.dir='';x.querySelector('.sort-arrow').textContent='';});
     th.dataset.dir=dir;arrow.textContent=dir==='asc'?'▲':'▼';
     const rows=[...body.querySelectorAll('tr')].filter(r=>r.children.length>idx&&!r.querySelector('td[colspan]'));
     rows.sort((a,b)=>a.children[idx].textContent.trim().localeCompare(b.children[idx].textContent.trim(),'ru',{numeric:true,sensitivity:'base'})*(dir==='asc'?1:-1));
     rows.forEach(r=>body.appendChild(r));window.trackerRenumber(table);
   });
 });
});
