/* Ambient infrastructure: bounded particles, 30 fps, no hidden-tab work. */
(() => {
 'use strict';
 const canvas=document.getElementById('ambient-network');
 if(!canvas)return;
 const ctx=canvas.getContext('2d'),motion=matchMedia('(prefers-reduced-motion: reduce)');
 let frame=0,last=0,width=0,height=0,points=[],ended=false;
 function resize(){
  width=innerWidth;height=innerHeight;
  const ratio=Math.min(devicePixelRatio||1,1.5);
  canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);ctx?.setTransform(ratio,0,0,ratio,0,0);
  const limited=(navigator.hardwareConcurrency||4)<=4 || width<768;
  const count=Math.min(limited?18:38,Math.ceil(width*height/45000));
  points=Array.from({length:count},()=>({x:Math.random()*width,y:Math.random()*height,vx:(Math.random()-.5)*.07,vy:-.025-Math.random()*.035}));
 }
 function draw(now){
  if(ended||document.hidden||motion.matches||!ctx){frame=0;return;}
  frame=requestAnimationFrame(draw);
  if(now-last<33)return;
  const delta=Math.min(now-last||33,60);last=now;ctx.clearRect(0,0,width,height);
  for(let i=0;i<points.length;i++){
   const p=points[i];p.x=(p.x+p.vx*delta+width)%width;p.y=(p.y+p.vy*delta+height)%height;
   ctx.fillStyle='#62b6ff55';ctx.beginPath();ctx.arc(p.x,p.y,1.2,0,Math.PI*2);ctx.fill();
   for(let j=i+1;j<points.length;j++){
    const q=points[j],distance=Math.hypot(p.x-q.x,p.y-q.y);if(distance>155)continue;
    ctx.strokeStyle=`rgba(77,163,255,${.1*(1-distance/155)})`;ctx.lineWidth=.7;ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(q.x,q.y);ctx.stroke();
   }
  }
 }
 function sync(){
  cancelAnimationFrame(frame);frame=0;last=0;
  document.documentElement.classList.toggle('page-hidden',document.hidden);
  document.querySelectorAll('.bg-video').forEach(video=>{if(document.hidden||motion.matches)video.pause();else video.play().catch(()=>{});});
  if(!ended&&!document.hidden&&!motion.matches&&ctx)frame=requestAnimationFrame(draw);
  else ctx?.clearRect(0,0,width,height);
 }
 let resizeTimer;
 window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(resize,150);});
 document.addEventListener('visibilitychange',sync);motion.addEventListener('change',sync);
 window.addEventListener('pagehide',()=>{ended=true;clearTimeout(resizeTimer);sync();});
 window.addEventListener('pageshow',()=>{ended=false;sync();});
 resize();sync();
})();
