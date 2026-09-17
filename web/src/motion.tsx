import {useEffect,useLayoutEffect,useRef,useState,type RefObject} from 'react';

export function useReducedMotion(){
  const [reduced,setReduced]=useState(()=>matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(()=>{const media=matchMedia('(prefers-reduced-motion: reduce)');const update=()=>setReduced(media.matches);media.addEventListener('change',update);return()=>media.removeEventListener('change',update);},[]);
  return reduced;
}

export function usePresence(show:boolean,reduced:boolean,duration=220){
  const [present,setPresent]=useState(show);
  useEffect(()=>{if(show){setPresent(true);return;}if(reduced){setPresent(false);return;}const timer=setTimeout(()=>setPresent(false),duration);return()=>clearTimeout(timer);},[show,reduced,duration]);
  return show||present;
}

export function useButtonRipples(reduced:boolean){
  useEffect(()=>{
    if(reduced)return;
    const selector='.send,.new-button,.direction-options button,.source-trigger,.more-questions,.followup,.answer-toolbar button,.source-actions button,.history';
    const animations=new Set<Animation>();
    const start=(event:PointerEvent|KeyboardEvent)=>{
      if(event instanceof KeyboardEvent&&(!['Enter',' '].includes(event.key)||event.repeat))return;
      const button=(event.target as Element)?.closest<HTMLButtonElement>(selector);
      if(!button||button.disabled)return;
      const box=button.getBoundingClientRect(),size=Math.max(box.width,box.height)*2;
      const wave=document.createElement('span');wave.className='button-ripple';wave.setAttribute('aria-hidden','true');
      const pointer=event instanceof PointerEvent;
      Object.assign(wave.style,{width:`${size}px`,height:`${size}px`,left:`${(pointer?event.clientX-box.left:box.width/2)-size/2}px`,top:`${(pointer?event.clientY-box.top:box.height/2)-size/2}px`});
      button.append(wave);
      const animation=wave.animate([{transform:'scale(.05)',opacity:.25},{transform:'scale(1)',opacity:0}],{duration:520,easing:'cubic-bezier(.16,1,.3,1)'});
      animations.add(animation);const clear=()=>{wave.remove();animations.delete(animation);};animation.onfinish=clear;animation.oncancel=clear;
    };
    document.addEventListener('pointerdown',start);document.addEventListener('keydown',start);
    return()=>{document.removeEventListener('pointerdown',start);document.removeEventListener('keydown',start);for(const a of animations)a.cancel();};
  },[reduced]);
}

export function useAutoInput(input:RefObject<HTMLTextAreaElement|null>,text:string,visible:boolean,reduced:boolean){
  useLayoutEffect(()=>{
    const node=input.current;if(!node||!visible||!node.getClientRects().length)return;
    const before=node.getBoundingClientRect().height;node.style.height='auto';
    const height=Math.min(180,Math.max(64,node.scrollHeight));node.style.height=`${height}px`;node.style.overflowY=node.scrollHeight>180?'auto':'hidden';
    if(reduced||Math.abs(before-height)<1)return;
    const animation=node.animate([{height:`${before}px`},{height:`${height}px`}],{duration:160,easing:'cubic-bezier(.2,.8,.2,1)'});
    return()=>animation.cancel();
  },[input,text,visible,reduced]);
}

export function DirectionSelection({selected,count}:{selected:number|null;count:number}){
  const marker=useRef<HTMLSpanElement|null>(null);
  const [box,setBox]=useState({x:0,y:0,width:0,height:0});
  useLayoutEffect(()=>{
    const parent=marker.current?.parentElement;if(!parent)return;
    const measure=()=>{const button=parent.querySelector<HTMLButtonElement>('button[aria-pressed="true"]');if(button)setBox({x:button.offsetLeft,y:button.offsetTop,width:button.offsetWidth,height:button.offsetHeight});};
    measure();const observer=new ResizeObserver(measure);observer.observe(parent);return()=>observer.disconnect();
  },[selected,count]);
  return <span ref={marker} className="direction-selection" aria-hidden="true" style={{transform:`translate(${box.x}px,${box.y}px)`,width:box.width,height:box.height,opacity:selected===null?0:1}}/>;
}

export function WaterArt(){return <svg className="water-art" viewBox="0 0 360 180" fill="none" aria-hidden="true">
  <defs><linearGradient id="water-ink" x1="35" y1="150" x2="300" y2="20" gradientUnits="userSpaceOnUse"><stop stopColor="#bdd9cc" stopOpacity=".15"/><stop offset=".55" stopColor="#5b988b" stopOpacity=".65"/><stop offset="1" stopColor="#bfd7c9" stopOpacity=".25"/></linearGradient></defs>
  <g stroke="url(#water-ink)" strokeWidth="1.2"><path d="M5 158C83 179 105 84 181 74S279 123 353 25"/><path d="M5 146C82 169 108 69 182 64S275 112 353 15"/><path d="M14 167C94 177 116 93 186 87S281 135 360 43"/><ellipse cx="227" cy="66" rx="90" ry="32" transform="rotate(-18 227 66)"/><ellipse cx="227" cy="66" rx="65" ry="23" transform="rotate(-18 227 66)"/><ellipse cx="227" cy="66" rx="39" ry="14" transform="rotate(-18 227 66)"/></g>
  <circle cx="227" cy="66" r="6" fill="#bca16c"/><circle cx="227" cy="66" r="11" stroke="#bca16c" strokeOpacity=".23"/>
</svg>;}

export function FlowGlyph(){return <svg viewBox="0 0 36 20" fill="none" aria-hidden="true"><path d="M2 7C8 1 13 1 18 7s10 6 16 0M2 14c6-6 11-6 16 0s10 6 16 0" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>;}
