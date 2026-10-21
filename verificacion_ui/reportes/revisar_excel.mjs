import fs from 'node:fs/promises';
import {FileBlob,SpreadsheetFile} from '@oai/artifact-tool';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load('verificacion_ui/reportes/Inventario_actual.xlsx'));
console.log((await wb.inspect({kind:'region',sheetId:'Reporte',range:'A6:F10',maxChars:1500,tableMaxRows:5,tableMaxCols:6})).ndjson);
const png=await wb.render({sheetName:'Reporte',range:'A1:F16',scale:1.3,format:'png'});
await fs.writeFile('verificacion_ui/reportes/excel.png',new Uint8Array(await png.arrayBuffer()));
