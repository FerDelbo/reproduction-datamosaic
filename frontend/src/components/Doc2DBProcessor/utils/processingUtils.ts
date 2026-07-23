import { ProcessingStep } from '../types';
import { MODEL_OPTIONS } from '../constants';

export const resolveDisplayTableName = (
  tableName?: string,
  schema?: string | { tables?: Array<{ name?: string }>; table_name?: string }
): string => {
  if (tableName && tableName.trim()) {
    return tableName.trim();
  }

  let parsedSchema = schema;
  if (typeof parsedSchema === 'string' && parsedSchema.trim()) {
    try {
      parsedSchema = JSON.parse(parsedSchema);
    } catch {
      return 'unknown';
    }
  }

  if (parsedSchema && typeof parsedSchema === 'object') {
    const tables = parsedSchema.tables || [];
    const names = tables
      .map((table) => table.name?.trim())
      .filter((name): name is string => Boolean(name));

    if (names.length === 1) {
      return names[0];
    }
    if (names.length > 1) {
      return names.join('_');
    }
    if (parsedSchema.table_name?.trim()) {
      return parsedSchema.table_name.trim();
    }
  }

  return 'unknown';
};

export const resolveTableNameForRequest = (tableNames: string[]): string => {
  if (tableNames.length === 1) {
    return tableNames[0];
  }
  if (tableNames.length > 1) {
    return '';
  }
  return 'default_table';
};

export const normalizeModelValue = (modelValue: string): string => {
  if (!modelValue) return 'gpt-4o';
  
  const isValidModel = MODEL_OPTIONS.some(option => 
    option.value === modelValue && option.value !== 'settings'
  );
  
  return isValidModel ? modelValue : 'gpt-4o';
};

export const getStepDisplayName = (stepName: string) => {
  if (stepName?.includes('orchestrator_init')) return 'Orchestrator - Initialization';
  if (stepName?.includes('orchestrator_analyze')) return 'Orchestrator - Requirement Analysis';
  if (stepName?.includes('orchestrator_finalized')) return 'Orchestrator - Process Completed';
  
  if (stepName?.includes('extractor_start')) return 'Extractor - Start Extraction';
  if (stepName?.includes('extractor_completed')) return 'Extractor - Extraction Completed';
  if (stepName?.includes('extractor_failed')) return 'Extractor - Extraction Failed';
  
  if (stepName?.includes('locator_document_')) {
    const tableMatch = stepName.match(/locator_document_(.+)/);
    if (tableMatch) {
      const tableName = tableMatch[1];
      return `Document Locator - Table ${tableName}`;
    }
    return 'Document Locator - Document Fragment Locator';
  }
  
  if (stepName?.includes('warm_start_cell_fix')) {
    if (stepName?.includes('_error')) {
      return 'Warm Start Extract - Cell Fix Error';
    }
    const docMatch = stepName.match(/warm_start_cell_fix_document_(\d+)/);
    if (docMatch) {
      const docNum = parseInt(docMatch[1]);
      return `Warm Start Extract- Document ${docNum} Cell Fix`;
    }
    return 'Warm Start Extract - Cell Level Precise Fix';
  }
  
  if (stepName?.includes('extractor_relation_detailed')) {
    if (stepName?.includes('_error')) {
      const tableMatch = stepName.match(/extractor_relation_detailed_(.+)_error/);
      if (tableMatch) {
        const tableName = tableMatch[1];
        return `Relation Table ${tableName} - Extraction Failed`;
      }
      return 'Relation Table Extraction Failed';
    }
    const tableMatch = stepName.match(/extractor_relation_detailed_(.+)/);
    if (tableMatch) {
      const tableName = tableMatch[1];
      return `extractor_relation_table_${tableName}`;
    }
    return 'extractor_relation_table_detailed';
  }
  
  if (stepName?.includes('extractor_document_') && stepName?.includes('_detailed')) {
    const docMatch = stepName.match(/extractor_document_(\d+)_detailed/);
    if (docMatch) {
      const docNum = parseInt(docMatch[1]) + 1;
      return `extractor_document_${docNum}_detailed`;
    }
  }
  
  if (stepName?.includes('schema_parsing')) return 'Schema - Structure Parsing';
  if (stepName?.includes('document_conversion')) return 'Document Conversion';
  if (stepName?.includes('data_extraction')) return 'Data Extraction Execution';
  
  if (stepName?.includes('verifier_start')) return 'Verifier - Start Verification';
  if (stepName?.includes('verifier_completed')) return 'Verifier - Verification Completed';
  if (stepName?.includes('verifier_failed')) return 'Verifier - Verification Failed';
  
  if (stepName?.includes('verifier_table_') && stepName?.includes('_detailed')) {
    const tableMatch = stepName.match(/verifier_table_(.+)_detailed/);
    if (tableMatch) {
      const tableName = tableMatch[1];
      return `Verifier - Table ${tableName} Verification Details`;
    }
  }
  
  if (stepName?.match(/verifier_.*_round_\d+$/)) {
    const roundMatch = stepName.match(/round_(\d+)$/);
    if (roundMatch) {
      const round = roundMatch[1];
      if (stepName.includes('start')) {
        return `Verifier - Round ${round} Verification Start`;
      } else if (stepName.includes('completed')) {
        return `Verifier - Round ${round} Verification Completed`;
      }
    }
  }
  
  if (stepName?.includes('fixer_start')) return 'Fixer - Start Fixing';
  if (stepName?.includes('fixer_completed')) return 'Fixer - Fixing Completed';
  if (stepName?.includes('fixer_failed')) return 'Fixer - Fixing Failed';
  
  if (stepName?.includes('初始化') || stepName?.includes('Initialization')) return 'System Initialization';
  if (stepName?.includes('需求分析') || stepName?.includes('Requirement Analysis')) return 'Requirement Analysis';
  if (stepName?.includes('数据提取') || stepName?.includes('Data Extraction')) return 'Data Extraction';
  if (stepName?.includes('数据验证') || stepName?.includes('Data Verification')) return 'Data Verification';
  if (stepName?.includes('数据修复') || stepName?.includes('Data Fixing')) return 'Data Fixing';
  if (stepName?.includes('处理完成') || stepName?.includes('Processing Completed')) return 'Processing Completed';
  
  return stepName || 'Unknown Step';
};

export const formatTableData = (tableData: any): string => {
  if (!tableData || !tableData.headers || !tableData.rows) {
    return '';
  }

  const headers = tableData.headers;
  const rows = tableData.rows;

  let markdown = '| ' + headers.join(' | ') + ' |\n';
  markdown += '|' + headers.map(() => ' --- ').join('|') + '|\n';

  rows.forEach((row: any) => {
    const values = headers.map((header: string) => {
      const cell = row[header];
      return cell ? String(cell.value || '') : '';
    });
    markdown += '| ' + values.join(' | ') + ' |\n';
  });

  return markdown;
};

export const validateJsonSchema = (jsonString: string): boolean => {
  try {
    if (!jsonString || !jsonString.trim()) return false;
    const parsed = JSON.parse(jsonString.trim());
    return !!(
      parsed.table_name && 
      parsed.table_name.trim() &&
      Array.isArray(parsed.columns) && 
      parsed.columns.length > 0 &&
      parsed.columns.some((col: any) => col.name && col.name.trim())
    );
  } catch {
    return false;
  }
};

export const containsTable = (content: string): boolean => {
  return content.includes('<TABLE BEGIN>') && content.includes('<TABLE END>');
};

export const extractTableContent = (content: string): string => {
  const match = content.match(/<TABLE BEGIN>([\s\S]*?)<TABLE END>/);
  return match ? match[1].trim() : '';
};

const isMarkdownTable = (lines: string[], startIndex: number): number => {
  if (startIndex + 2 >= lines.length) return -1;
  
  const headerLine = lines[startIndex];
  const separatorLine = lines[startIndex + 1];
  
  if (headerLine.includes('|') && separatorLine.match(/^\s*\|?\s*[-:]+\s*(\|\s*[-:]+\s*)+\|?\s*$/)) {
    let endIndex = startIndex + 2;
    while (endIndex < lines.length && lines[endIndex].includes('|')) {
      endIndex++;
    }
    return endIndex;
  }
  
  return -1;
};

export const splitContentWithTables = (content: string): Array<{type: 'text' | 'table', content: string}> => {
  const parts: Array<{type: 'text' | 'table', content: string}> = [];
  
  const tableRegex = /<TABLE BEGIN>([\s\S]*?)<TABLE END>/g;
  let processedContent = content;
  const tableMatches: Array<{index: number, length: number, content: string}> = [];
  
  let match;
  while ((match = tableRegex.exec(content)) !== null) {
    tableMatches.push({
      index: match.index,
      length: match[0].length,
      content: match[1].trim()
    });
  }
  
  const lines = content.split('\n');
  let lineIndex = 0;
  let currentText: string[] = [];
  
  const isInTaggedTable = (charIndex: number): boolean => {
    return tableMatches.some(tm => charIndex >= tm.index && charIndex < tm.index + tm.length);
  };
  
  while (lineIndex < lines.length) {
    const currentLineStart = lines.slice(0, lineIndex).join('\n').length + (lineIndex > 0 ? 1 : 0);
    
    if (isInTaggedTable(currentLineStart)) {
      currentText.push(lines[lineIndex]);
      lineIndex++;
      continue;
    }
    
    const tableEndIndex = isMarkdownTable(lines, lineIndex);
    
    if (tableEndIndex > lineIndex) {
      
      if (currentText.length > 0) {
        const textContent = currentText.join('\n').trim();
        if (textContent) {
          parts.push({ type: 'text', content: textContent });
        }
        currentText = [];
      }
      
      const tableContent = lines.slice(lineIndex, tableEndIndex).join('\n').trim();
      if (tableContent) {
        parts.push({ type: 'table', content: tableContent });
      }
      
      lineIndex = tableEndIndex;
    } else {
      currentText.push(lines[lineIndex]);
      lineIndex++;
    }
  }
  
  if (currentText.length > 0) {
    const textContent = currentText.join('\n').trim();
    if (textContent) {
      parts.push({ type: 'text', content: textContent });
    }
  }
  
  if (parts.length === 0) {
    parts.push({ type: 'text', content: content });
  }
  
  return parts;
};

export const splitContentForDocumentInput = (content: string): Array<{type: 'text', content: string}> => {
  return [{ type: 'text', content: content }];
};

export const renderStreamMessageContent = (content: any): string => {
  if (typeof content === 'string') {
    return content;
  }
  
  if (typeof content === 'object') {
    if (content.step && content.description) {
      return `Step: ${content.step}\nDescription: ${content.description}${content.details ? '\nDetails: ' + JSON.stringify(content.details, null, 2) : ''}`;
    }
    
    return JSON.stringify(content, null, 2);
  }
  
  return String(content);
};

const tryFetchResultJson = async (runId: string, projectId?: string, retryCount: number = 3): Promise<any> => {
  for (let attempt = 1; attempt <= retryCount; attempt++) {
    try {
      const apiUrl = projectId && projectId !== 'default-project'
        ? `/api/projects/${projectId}/files/content`
        : `/api/files/content`;
      
      const filepath = `output/${runId}/result.json`;
      const url = new URL(apiUrl, window.location.origin);
      url.searchParams.set('filepath', filepath);
      
      const response = await fetch(url.toString(), {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        }
      });
      
      if (!response.ok) {
        if (attempt < retryCount) {
          const delay = attempt * 500;
          await new Promise(resolve => setTimeout(resolve, delay));
          continue;
        }
        
        return null;
      }
      
      const data = await response.json();
      
      if (data.content) {
        const resultData = JSON.parse(data.content);
        return resultData;
      }
      
      return null;
    } catch (error) {
      if (attempt < retryCount) {
        const delay = attempt * 500;
        await new Promise(resolve => setTimeout(resolve, delay));
        continue;
      }
      
      return null;
    }
  }
  
  return null;
};

const buildTablesFromResultJson = (resultData: any): Array<{tableName: string, tableData: string, rowCount: number}> => {
  const allTables: Array<{tableName: string, tableData: string, rowCount: number}> = [];
  
  if (!resultData || typeof resultData !== 'object' || !resultData.tables) {
    return allTables;
  }
  
  const tables = resultData.tables;
  
  for (const [tableName, tableRows] of Object.entries(tables)) {
    if (!Array.isArray(tableRows) || tableRows.length === 0) {
      continue;
    }
    
    const firstRow = tableRows[0];
    if (!firstRow || typeof firstRow !== 'object') {
      continue;
    }
    
    const headers = Object.keys(firstRow);
    
    let markdown = '| ' + headers.join(' | ') + ' |\n';
    markdown += '|' + headers.map(() => ' --- ').join('|') + '|\n';
    
    for (const row of tableRows) {
      const values = headers.map((header: string) => String(row[header] || ''));
      markdown += '| ' + values.join(' | ') + ' |\n';
    }
    
    allTables.push({
      tableName: tableName,
      tableData: markdown,
      rowCount: tableRows.length
    });
  }
  
  return allTables;
};

export const extractAllTablesFromSnapshot = async (status: any, projectId?: string) => {
  const resultData = status?.result_context?.result_data || status?.result?.result_data;
  
  if (resultData) {
    const tables = buildTablesFromResultJson(resultData);
    if (tables.length > 0) {
      return tables;
    }
  }
  
  const runId = status?.run_id || status?.result?.run_id || status?.result_context?.run_id;
  
  if (runId) {
    const fetchedResultData = await tryFetchResultJson(runId, projectId);
    
    if (fetchedResultData) {
      const tables = buildTablesFromResultJson(fetchedResultData);
      if (tables.length > 0) {
        return tables;
      }
    }
  }
  
  const allTables: Array<{tableName: string, tableData: string, rowCount: number}> = [];
  
  if (status?.result_context?.snapshots && typeof status.result_context.snapshots === 'object') {
    const snapshotsDict = status.result_context.snapshots;
    const tableNames = Object.keys(snapshotsDict);
    
    for (const tableName of tableNames) {
      const snapshot = snapshotsDict[tableName];
      
      if (snapshot && snapshot.rows && Array.isArray(snapshot.rows) && snapshot.rows.length > 0) {
        const firstRow = snapshot.rows[0];
        const headers = Object.keys(firstRow.cells || {});
        
        if (headers.length > 0) {
          const tableData = {
            headers: headers,
            rows: snapshot.rows.map((row: any) => {
              const rowData: any = {};
              headers.forEach(header => {
                const cell = row.cells[header];
                rowData[header] = {
                  value: cell?.value !== undefined ? cell.value : (cell?.best?.value || '')
                };
              });
              return rowData;
            })
          };
          
          const markdown = formatTableData(tableData);
          
          allTables.push({
            tableName: tableName,
            tableData: markdown,
            rowCount: snapshot.rows.length
          });
        }
      }
    }
  }
  else {
    let snapshot = null;
    let tableName = 'extracted_table';
    
    if (status?.result_context?.snapshot) {
      snapshot = status.result_context.snapshot;
      tableName = status?.result_context?.summary?.table_name || snapshot.table || tableName;
    } else if (status?.result?.snapshot) {
      snapshot = status.result.snapshot;
      tableName = status?.result?.summary?.table_name || snapshot.table || tableName;
    }
    
    if (snapshot && snapshot.rows && Array.isArray(snapshot.rows) && snapshot.rows.length > 0) {
      const firstRow = snapshot.rows[0];
      const headers = Object.keys(firstRow.cells || {});
      
      if (headers.length > 0) {
        const tableData = {
          headers: headers,
          rows: snapshot.rows.map((row: any) => {
            const rowData: any = {};
            headers.forEach(header => {
              const cell = row.cells[header];
              rowData[header] = {
                value: cell?.value !== undefined ? cell.value : (cell?.best?.value || '')
              };
            });
            return rowData;
          })
        };
        
        const markdown = formatTableData(tableData);
        
        allTables.push({
          tableName: tableName,
          tableData: markdown,
          rowCount: snapshot.rows.length
        });
      }
    }
    
    if (allTables.length === 0 && status?.result?.table_data) {
      const markdown = formatTableData(status.result.table_data);
      if (markdown.trim()) {
        allTables.push({
          tableName: status?.result?.summary?.table_name || 'extracted_table',
          tableData: markdown,
          rowCount: status.result.table_data.rows?.length || 0
        });
      }
    }
  }
  
  return allTables;
};



