import Papa from 'papaparse';
import readExcel from 'read-excel-file/universal';

export type Sheet = {name:string; rows:string[][]};
const MAX_ROWS=20001,MAX_COLS=100,MAX_CELLS=250000;
function normalise(rows:unknown[][]):string[][]{
  if(rows.length>MAX_ROWS||rows.some(r=>r.length>MAX_COLS)||rows.reduce((n,r)=>n+r.length,0)>MAX_CELLS)
    throw new Error('表格过大，请拆分为不超过 20,000 行、100 列、250,000 个单元格的文件。');
  return rows.filter(r=>r.some(v=>v!==null&&v!==undefined&&v!=='')).map(r=>r.map(v=>{
    const s=v instanceof Date?v.toISOString():v==null?'':String(v);
    if(s.length>10000)throw new Error('单元格内容过长，请将每格控制在 10,000 字以内。');
    return s;
  }));
}
// Inspect the ZIP directory before expanding XLSX, and never follow archive paths.
function inspectZip(buffer:ArrayBuffer){
  const v=new DataView(buffer);let end=-1;
  for(let i=v.byteLength-22;i>=Math.max(0,v.byteLength-65557);i--){if(v.getUint32(i,true)===0x06054b50){end=i;break;}}
  if(end<0)throw new Error('这不是有效的 Excel 工作簿，请另存为 .xlsx 后重试。');
  const count=v.getUint16(end+10,true);let offset=v.getUint32(end+16,true),total=0;
  if(count>2000)throw new Error('工作簿内容过多，请精简工作表后重试。');
  for(let i=0;i<count;i++){
    if(offset+46>v.byteLength||v.getUint32(offset,true)!==0x02014b50)throw new Error('工作簿已损坏，请重新导出。');
    if(v.getUint16(offset+8,true)&1)throw new Error('暂不支持加密工作簿，请移除密码后重试。');
    total+=v.getUint32(offset+24,true);
    if(total>32*1024*1024)throw new Error('工作簿解压后超过 32 MB，请拆分后重试。');
    offset+=46+v.getUint16(offset+28,true)+v.getUint16(offset+30,true)+v.getUint16(offset+32,true);
  }
}
self.onmessage=async(event:MessageEvent<{file:File;encoding:string}>)=>{
  try{
    const {file,encoding}=event.data;const buffer=await file.arrayBuffer();let sheets:Sheet[];
    if(file.name.toLowerCase().endsWith('.csv')){
      const input=new TextDecoder(encoding,{fatal:true}).decode(buffer).replace(/^\uFEFF/,'');
      const result=Papa.parse<string[]>(input,{skipEmptyLines:'greedy',dynamicTyping:false});
      if(result.errors.some(e=>e.code!=='UndetectableDelimiter'))throw new Error('CSV 的引号或分隔符不完整，请检查文件后重试。');
      sheets=[{name:'数据表',rows:normalise(result.data)}];
    }else{
      inspectZip(buffer);
      const result=await readExcel(buffer,{parseNumber:s=>s});
      if(result.length>20)throw new Error('工作表超过 20 张，请拆分文件后重试。');
      sheets=result.map(s=>({name:s.sheet,rows:normalise(s.data)}));
    }
    self.postMessage({sheets});
  }catch(error){self.postMessage({error:error instanceof TypeError?'文件编码无法识别，请试试 GB18030 编码，或重新导出文件。':error instanceof Error?error.message:'无法读取文件，请重新导出后重试。'});}
};
