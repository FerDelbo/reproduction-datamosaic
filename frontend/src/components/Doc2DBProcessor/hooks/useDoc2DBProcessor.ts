import { useState, useEffect, useRef, useCallback } from 'react';
import { ProcessingStatus, FileItem, SchemaForm, ColumnField, MemoryData } from '../types';
import { normalizeModelValue, resolveDisplayTableName, resolveTableNameForRequest, validateJsonSchema } from '../utils/processingUtils';
import { 
  connectToSignals, 
  createDoc2DBSignalCallbacks,
  WebSocketSignalClient 
} from '../../../services/websocketSignals';

export const useDoc2DBProcessor = (
  selectedFiles: FileItem[],
  onTaskCompleted?: (taskId: string) => void,
  onHistoryFilesLoad?: (files: FileItem[]) => void
) => {
  const [processing, setProcessing] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [status, setStatus] = useState<ProcessingStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [configCollapsed, setConfigCollapsed] = useState(false);
  
  const [isHistoryMode, setIsHistoryMode] = useState(false);
  const [historyTaskTitle, setHistoryTaskTitle] = useState<string>('');
  
  const [currentModel, setCurrentModel] = useState('gpt-4o');
  
  const [settingsDialogOpen, setSettingsDialogOpen] = useState(false);
  const [apiKey, setApiKey] = useState('');
  const [apiUrl, setApiUrl] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');
  
  const [pollingInterval, setPollingInterval] = useState<NodeJS.Timeout | null>(null);
  const [shouldKeepPolling, setShouldKeepPolling] = useState(false);
  
  const [wsClient, setWsClient] = useState<WebSocketSignalClient | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  
  const [memoryData, setMemoryData] = useState<MemoryData | null>(null);
  const [memoryLoading, setMemoryLoading] = useState(false);
  
  const [inputMode, setInputMode] = useState<'instruction' | 'schema'>('instruction');
  const [schemaMode, setSchemaMode] = useState<'json' | 'form'>('form');
  const [schemaInput, setSchemaInput] = useState('');
  const [instructionInput, setInstructionInput] = useState('');
  const [schemaForm, setSchemaForm] = useState<SchemaForm>({
    tables: [{
      id: 'table_1',
      name: '',
      tableType: 'entity', // Default to entity table
      fields: [{ name: '', type: 'TEXT', description: '' }]
    }],
    relations: []
  });
  const [currentTableIndex, setCurrentTableIndex] = useState(0);
  
  const [processingMode, setProcessingMode] = useState<'auto' | 'serial' | 'parallel'>('serial');
  const [maxConcurrentTables, setMaxConcurrentTables] = useState(3);
  
  const [documentMode, setDocumentMode] = useState<'single' | 'multi'>('single');
  
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const fetchCurrentModel = async () => {
    try {
      const response = await fetch('/api/settings');
      if (response.ok) {
        const data = await response.json();
        if (data && data.model) {
          const modelFromBackend = data.model;
          const normalizedModel = normalizeModelValue(modelFromBackend);
          
          if (normalizedModel !== modelFromBackend) {
            console.warn('Backend returned unknown model:', modelFromBackend, 'Using normalized:', normalizedModel);
          }
          
          setCurrentModel(normalizedModel);
        } else {
          setCurrentModel('gpt-4o');
        }
        
        setApiKey(data.api_key || '');
        setApiUrl(data.api_url || '');
      } else {
        throw new Error('Failed to fetch settings');
      }
    } catch (error) {
      console.error('Error fetching current model:', error);
      setCurrentModel('gpt-4o');
    }
  };

  const handleModelChange = async (newModel: string) => {
    if (newModel === 'settings') {
      setSettingsDialogOpen(true);
      return;
    }
    
    const normalizedModel = normalizeModelValue(newModel);
    if (normalizedModel !== newModel) {
      console.warn('Invalid model selected:', newModel, 'Using normalized:', normalizedModel);
    }
    
    const previousModel = currentModel;
    setCurrentModel(normalizedModel);
    
    try {
      const response = await fetch('/api/settings', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          model: normalizedModel
        })
      });
      
      if (!response.ok) {
        throw new Error('Failed to update model');
      }
    } catch (error) {
      console.error('Error updating model:', error);
      setCurrentModel(previousModel);
    }
  };

  const handleSaveSettings = async () => {
    setIsSaving(true);
    setSaveMessage('');
    
    try {
      const response = await fetch('/api/settings', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          model: currentModel,
          api_key: apiKey,
          api_url: apiUrl
        })
      });

      if (response.ok) {
        setSaveMessage('Settings saved');
        setTimeout(() => {
          setSaveMessage('');
          setSettingsDialogOpen(false);
        }, 1500);
      } else {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to save settings');
      }
    } catch (error) {
      console.error('Error saving settings:', error);
      setSaveMessage(`Save failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsSaving(false);
    }
  };

  const fetchTaskStatus = useCallback(async () => {
    if (!taskId) return;
    
    try {
      const response = await fetch(`/api/doc2db/status/${taskId}`);
      
      if (response.ok) {
        const statusData = await response.json();
        
        setStatus(prevStatus => {
          if (!prevStatus) {
            return statusData;
          }
          
          return {
            ...prevStatus,
            ...statusData,
            steps: statusData.steps && statusData.steps.length > 0 
              ? statusData.steps 
              : prevStatus.steps
          };
        });
        
        if (statusData.status === 'completed' || statusData.status === 'failed') {
          setProcessing(false);
          setShouldKeepPolling(false);
          
          if (statusData.status === 'completed' && onTaskCompleted && taskId) {
            setTimeout(() => {
              onTaskCompleted(taskId);
            }, 1000);
          }
        }
      } else {
        const errorData = await response.json().catch(() => ({ error: 'Unknown error' }));
        
        if (response.status === 404) {
          setShouldKeepPolling(false);
          setProcessing(false);
          setTaskId(null);
          return;
        }
        
        console.error('Failed to fetch status:', errorData.error);
        setError(errorData.error || 'Failed to fetch status');
        setProcessing(false);
        setShouldKeepPolling(false);
      }
    } catch (error) {
      console.error('Error fetching status:', error);
    }
  }, [taskId, onTaskCompleted]);

  const startProcessing = async () => {
    if (processing || taskId) {
      return;
    }

    try {
      
      setError(null);
      setStatus(null);
      setTaskId(null);
      setMemoryData(null); // Clear old memory data
      setProcessing(true);
      setShouldKeepPolling(true);
      setConfigCollapsed(true);
      
      let schemaData = '';
      let tableNameToUse = 'default_table';
      
      if (inputMode === 'schema') {
        if (schemaMode === 'form') {
          if (schemaForm.tables.length > 0) {
            const validTables = schemaForm.tables.filter(table => 
              table.name.trim() && table.fields.length > 0
            );
            
            const cleanedSchema = {
              metadata: {
                version: '1.0.0',
                generator: 'Doc2DB Schema Designer',
                generated_at: new Date().toISOString(),
                tables_count: validTables.length,
                relations_count: schemaForm.relations?.length || 0
              },
              tables: validTables.map(table => ({
                id: table.id,
                name: table.name.trim(),
                type: table.tableType || 'entity', // Map form tableType to JSON type
                fields: table.fields
                  .filter((field: ColumnField) => field.name.trim())
                  .map((field: ColumnField) => ({
                    name: field.name.trim(),
                    type: field.type,
                    description: field.description.trim(),
                    constraints: field.constraints
                  }))
              })),
              relations: schemaForm.relations || []
            };
            schemaData = JSON.stringify(cleanedSchema);
            tableNameToUse = resolveTableNameForRequest(
              validTables.map(table => table.name.trim())
            );
          }
        } else {
          try {
            const parsedSchema = JSON.parse(schemaInput.trim());
            
            if (parsedSchema.tables && Array.isArray(parsedSchema.tables)) {
              const cleanedSchema = {
                metadata: parsedSchema.metadata || {
                  version: '1.0.0',
                  generator: 'Doc2DB Schema Designer',
                  generated_at: new Date().toISOString(),
                  tables_count: parsedSchema.tables.length,
                  relations_count: parsedSchema.relations?.length || 0
                },
                tables: parsedSchema.tables
                  .filter((table: any) => table.name && table.name.trim())
                  .map((table: any) => ({
                    id: table.id || `table_${Math.random()}`,
                    name: table.name.trim(),
                    fields: (table.fields || [])
                      .filter((field: any) => field.name && field.name.trim())
                      .map((field: any) => ({
                        name: field.name.trim(),
                        type: field.type || 'TEXT',
                        description: field.description || '',
                        constraints: field.constraints
                      }))
                  })),
                relations: parsedSchema.relations || []
              };
              schemaData = JSON.stringify(cleanedSchema);
              tableNameToUse = resolveTableNameForRequest(
                cleanedSchema.tables.map((table: { name: string }) => table.name)
              );
            }
            else if (parsedSchema.table_name && Array.isArray(parsedSchema.columns) && parsedSchema.columns.length > 0) {
              const cleanedSchema = {
                table_name: parsedSchema.table_name.trim(),
                columns: parsedSchema.columns
                  .filter((col: any) => col.name && col.name.trim())
                  .map((col: any) => ({
                    name: col.name.trim(),
                    type: col.type || 'TEXT',
                    description: col.description || ''
                  }))
              };
              schemaData = JSON.stringify(cleanedSchema);
              tableNameToUse = cleanedSchema.table_name;
              }
          } catch (error) {
            console.error('Failed to parse JSON Schema:', error);
          }
        }
      }
      
      const requestData: any = {
        files: selectedFiles.map(f => f.filepath),
        table_name: tableNameToUse,
        nl_prompt: inputMode === 'instruction' ? instructionInput.trim() : '',
        schema: schemaData,
        input_mode: inputMode,
        model: currentModel,
        processing_mode: processingMode,
        max_concurrent_tables: maxConcurrentTables,
        document_mode: documentMode
      };
      
      if (inputMode === 'schema') {
        requestData.schema_mode = schemaMode;
      }
      
      if (requestData.nl_prompt === undefined) requestData.nl_prompt = '';
      if (requestData.schema === undefined) requestData.schema = '';
      if (requestData.table_name === undefined) requestData.table_name = 'default_table';
      
      const response = await fetch('/api/doc2db/process', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestData),
      });

      if (response.ok) {
        const result = await response.json();
        setTaskId(result.task_id);
        
        if (wsClient && wsConnected) {
          wsClient.subscribeToRun(result.task_id);
        }
      } else {
        let errorData;
        try {
          errorData = await response.json();
        } catch (parseError) {
          await response.text();
          errorData = { error: `HTTP ${response.status}: ${response.statusText}` };
        }
        setError(errorData.error || `Failed to start processing (${response.status})`);
        setProcessing(false);
        setShouldKeepPolling(false);
      }
    } catch (error) {
      console.error('Failed to start processing:', error);
      setError('Network error: Unable to start processing');
      setProcessing(false);
      setShouldKeepPolling(false);
    }
  };

  const fetchMemoryData = useCallback(async (runId: string) => {
    if (!runId) return;
    
    setMemoryLoading(true);
    try {
      const [snapshotRes, violationRes, fixRes] = await Promise.allSettled([
        fetch(`/api/memory/snapshots/${runId}`),
        fetch(`/api/memory/violations/${runId}`),
        fetch(`/api/memory/fixes/${runId}`)
      ]);

      const getData = async (result: PromiseSettledResult<Response>) => {
        if (result.status === 'fulfilled' && result.value.ok) {
          return await result.value.json();
        }
        return null;
      };

      const [snapshotsRaw, violationsRaw, fixesRaw] = await Promise.all([
        getData(snapshotRes),
        getData(violationRes),
        getData(fixRes)
      ]);

      let snapshots = null;
      if (snapshotsRaw) {
        if (snapshotsRaw.snapshots) {
          snapshots = Object.values(snapshotsRaw.snapshots);
        } else if (snapshotsRaw.snapshots_from_file) {
          snapshots = snapshotsRaw.snapshots_from_file;
        } else if (snapshotsRaw.snapshot) {
          snapshots = [snapshotsRaw.snapshot];
        } else if (Array.isArray(snapshotsRaw)) {
          snapshots = snapshotsRaw;
        }
      }

      let violations = null;
      if (violationsRaw) {
        if (violationsRaw.violations_by_table) {
          violations = violationsRaw.violations_by_table;
        } else if (violationsRaw.violations_from_file) {
          violations = violationsRaw.violations_from_file;
        } else if (violationsRaw.violations) {
          violations = violationsRaw.violations;
        } else if (Array.isArray(violationsRaw)) {
          violations = violationsRaw;
        }
      }


      let fixes = null;
      if (fixesRaw) {
        if (fixesRaw.fixes_by_table) {
          fixes = fixesRaw.fixes_by_table;
        } else if (fixesRaw.fixes_from_file) {
          fixes = fixesRaw.fixes_from_file;
        } else if (fixesRaw.fixes) {
          fixes = fixesRaw.fixes;
        } else if (Array.isArray(fixesRaw)) {
          fixes = fixesRaw;
        }
      }

      setMemoryData({
        snapshots,
        violations,
        fixes,
        summary: null
      });
    } catch (error) {
      console.error('Failed to fetch Memory data:', error);
      setMemoryData(null);
    } finally {
      setMemoryLoading(false);
    }
  }, []);

  const validateFormSchema = (): boolean => {
    return !!(
      schemaForm.tables.length > 0 &&
      schemaForm.tables.every(table => 
        table.name && 
        table.name.trim() &&
        table.fields.length > 0 &&
        table.fields.some(field => field.name && field.name.trim())
      )
    );
  };

  const addTable = () => {
    const newTableId = `table_${schemaForm.tables.length + 1}`;
    setSchemaForm(prev => ({
      ...prev,
      tables: [...prev.tables, {
        id: newTableId,
        name: '',
        tableType: 'entity', // Default to entity table
        fields: [{ name: '', type: 'TEXT', description: '' }]
      }]
    }));
    setCurrentTableIndex(schemaForm.tables.length);
  };

  const removeTable = (index: number) => {
    if (schemaForm.tables.length > 1) {
      setSchemaForm(prev => ({
        ...prev,
        tables: prev.tables.filter((_, i) => i !== index)
      }));
      if (currentTableIndex >= schemaForm.tables.length - 1) {
        setCurrentTableIndex(Math.max(0, currentTableIndex - 1));
      }
    }
  };

  const updateTableName = (index: number, name: string) => {
    setSchemaForm(prev => ({
      ...prev,
      tables: prev.tables.map((table, i) => 
        i === index ? { ...table, name } : table
      )
    }));
  };

  const updateTableType = (index: number, tableType: 'entity' | 'relation') => {
    setSchemaForm(prev => ({
      ...prev,
      tables: prev.tables.map((table, i) => 
        i === index ? { ...table, tableType } : table
      )
    }));
  };

  const addRelation = () => {
    const newRelationId = `rel_${(schemaForm.relations?.length || 0) + 1}`;
    setSchemaForm(prev => ({
      ...prev,
      relations: [...(prev.relations || []), {
        id: newRelationId,
        type: 'many-to-one' as const,
        from: { table: '', field: '' },
        to: { table: '', field: '' }
      }]
    }));
  };

  const removeRelation = (index: number) => {
    setSchemaForm(prev => ({
      ...prev,
      relations: (prev.relations || []).filter((_, i) => i !== index)
    }));
  };

  const updateRelation = (index: number, updates: Partial<any>) => {
    setSchemaForm(prev => ({
      ...prev,
      relations: (prev.relations || []).map((rel, i) => 
        i === index ? { ...rel, ...updates } : rel
      )
    }));
  };

  const addColumn = () => {
    setSchemaForm(prev => ({
      ...prev,
      tables: prev.tables.map((table, i) => 
        i === currentTableIndex 
          ? { ...table, fields: [...table.fields, { name: '', type: 'TEXT', description: '' }] }
          : table
      )
    }));
  };

  const removeColumn = (index: number) => {
    const currentTable = schemaForm.tables[currentTableIndex];
    if (currentTable && currentTable.fields.length > 1) {
      setSchemaForm(prev => ({
        ...prev,
        tables: prev.tables.map((table, i) => 
          i === currentTableIndex 
            ? { ...table, fields: table.fields.filter((_, fi) => fi !== index) }
            : table
        )
      }));
    }
  };

  const updateColumn = (index: number, field: keyof ColumnField, value: string) => {
    setSchemaForm(prev => ({
      ...prev,
      tables: prev.tables.map((table, i) => 
        i === currentTableIndex 
          ? {
              ...table,
              fields: table.fields.map((col, fi) => 
                fi === index ? { ...col, [field]: value } : col
              )
            }
          : table
      )
    }));
  };

  const convertFormToJson = () => {
    const jsonSchema = JSON.stringify({
      metadata: {
        version: '1.0.0',
        generator: 'Doc2DB Schema Designer',
        generated_at: new Date().toISOString(),
        tables_count: schemaForm.tables.length,
        relations_count: schemaForm.relations?.length || 0
      },
      tables: schemaForm.tables.map(table => ({
        ...table,
        type: table.tableType || 'entity', // Map form tableType to JSON type
        tableType: undefined // Remove tableType field
      })),
      relations: schemaForm.relations || []
    }, null, 2);
    setSchemaInput(jsonSchema);
  };

  const convertJsonToForm = () => {
    try {
      const parsed = JSON.parse(schemaInput);
      
      if (parsed.tables && Array.isArray(parsed.tables)) {
        setSchemaForm({
          metadata: parsed.metadata,
          tables: parsed.tables.map((table: any) => ({
            id: table.id || `table_${Math.random()}`,
            name: table.name || '',
            tableType: table.type || 'entity', // Map JSON type field to form tableType
            fields: (table.fields || table.attributes || []).map((field: any) => ({
              name: field.name || '',
              type: field.type || 'TEXT',
              description: field.description || '',
              constraints: field.constraints
            }))
          })),
          relations: parsed.relations || []
        });
        setCurrentTableIndex(0);
      }
      else if (parsed.table_name && Array.isArray(parsed.columns)) {
        setSchemaForm({
          tables: [{
            id: 'table_1',
            name: parsed.table_name,
            tableType: 'entity', // Default to entity table
            fields: parsed.columns.map((col: any) => ({
              name: col.name || '',
              type: col.type || 'TEXT',
              description: col.description || ''
            }))
          }],
          relations: []
        });
        setCurrentTableIndex(0);
      }
    } catch (error) {
      console.error('JSON parsing failed:', error);
    }
  };

  useEffect(() => {
    if (!taskId) {
      if (pollingInterval) {
        clearInterval(pollingInterval);
        setPollingInterval(null);
      }
      return;
    }
    
    if (taskId && shouldKeepPolling) {
      if (pollingInterval) {
        clearInterval(pollingInterval);
      }
      
      fetchTaskStatus();
      
      const interval = setInterval(fetchTaskStatus, 2000);
      setPollingInterval(interval);
      
      return () => {
        clearInterval(interval);
      };
    } else if (!shouldKeepPolling) {
      if (pollingInterval) {
        clearInterval(pollingInterval);
        setPollingInterval(null);
      }
    }
  }, [taskId, shouldKeepPolling, fetchTaskStatus]);

  useEffect(() => {
    if (status && status.steps && status.steps.length > 0 && scrollContainerRef.current) {
      scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
    }
  }, [status, status?.steps?.length]);

  useEffect(() => {
    fetchCurrentModel();
    initializeWebSocket();
  }, []);
  
  const initializeWebSocket = async () => {
    try {
      const callbacks = createDoc2DBSignalCallbacks(
        (step) => {
          setStatus(prevStatus => {
            if (!prevStatus) return prevStatus;
            
            const newSteps = [...(prevStatus.steps || [])];
            
            const existingIndex = newSteps.findIndex(s => {
              if (step.step_id && s.step_id) {
                return s.step_id === step.step_id;
              }
              
              const sameName = (s.step === step.step || s.step_name === step.step_name);
              const hasValidTimestamp = step.timestamp && s.timestamp;
              const sameTimestamp = hasValidTimestamp && s.timestamp === step.timestamp;
              const hasValidStartTime = step.start_time && s.start_time;
              const sameStartTime = hasValidStartTime && s.start_time === step.start_time;
              
              return sameName && (sameTimestamp || sameStartTime);
            });
            
            if (existingIndex >= 0) {
              newSteps[existingIndex] = { ...newSteps[existingIndex], ...step };
            } else {
              newSteps.push(step);
            }
            
            return {
              ...prevStatus,
              steps: newSteps,
              current_step: step.description || step.step || prevStatus.current_step
            };
          });
        },
        
        (data) => {
          setStatus(prevStatus => ({
            ...prevStatus,
            ...data
          }));
        },
        
        (error) => {
          console.error('❌ Received real-time error:', error);
          setError(typeof error === 'string' ? error : error.message || 'An error occurred during processing');
        }
      );
      
      const client = await connectToSignals(callbacks);
      setWsClient(client);
      setWsConnected(true);
    } catch (error) {
      console.error('WebSocket signal connection failed:', error);
      setWsConnected(false);
    }
  };
  
  useEffect(() => {
    return () => {
      if (wsClient) {
        wsClient.disconnect();
      }
    };
  }, [wsClient]);

  useEffect(() => {
    const checkHistoryTask = () => {
      if ((window as any).selectedHistoryTaskId && (window as any).selectedHistoryTaskDetails) {
        const historyTaskId = (window as any).selectedHistoryTaskId;
        const historyDetails = (window as any).selectedHistoryTaskDetails;
        
        setIsHistoryMode(true);
        setTaskId(historyTaskId);
        
        let convertedStatus = {
          ...historyDetails
        };

        if (historyDetails.result?.step_outputs && Array.isArray(historyDetails.result.step_outputs)) {
          convertedStatus.steps = historyDetails.result.step_outputs.map((stepOutput: any) => ({
            step_name: stepOutput.step,
            step: stepOutput.step,
            status: stepOutput.status,
            description: stepOutput.description,
            timestamp: stepOutput.timestamp,
            details: stepOutput.details,
            result: stepOutput.details,
            ...stepOutput
          }));
        } else if (historyDetails.steps && Array.isArray(historyDetails.steps) && historyDetails.steps.length > 0) {
          convertedStatus.steps = historyDetails.steps;
        } else {
          convertedStatus.steps = [];
        }
        
        if (historyDetails.result_context) {
          convertedStatus.result_context = historyDetails.result_context;
        }
        
        if (historyDetails.result) {
          convertedStatus.result = historyDetails.result;
        }
        
        setStatus(convertedStatus);
        setProcessing(false);
        setConfigCollapsed(false);
        
        setHistoryTaskTitle(
          resolveDisplayTableName(
            historyDetails.result?.summary?.table_name || historyDetails.table_name,
            historyDetails.request?.schema
          )
        );
        
        if (historyDetails.request) {
          const request = historyDetails.request;
          
          if (request.input_mode) {
            setInputMode(request.input_mode);
          } else {
            if (request.nl_prompt && request.nl_prompt.trim()) {
              setInputMode('instruction');
            } else if (request.schema && request.schema.trim()) {
              setInputMode('schema');
            }
          }
          
          if (request.nl_prompt) {
            setInstructionInput(request.nl_prompt);
          }
          
          if (request.schema) {
            try {
              const schemaData = typeof request.schema === 'string' 
                ? JSON.parse(request.schema) 
                : request.schema;
              
              if (request.schema_mode) {
                setSchemaMode(request.schema_mode);
              } else {
                setSchemaMode('form');
              }
              
              const jsonString = JSON.stringify(schemaData, null, 2);
              setSchemaInput(jsonString);
              
              if (schemaData.tables && Array.isArray(schemaData.tables)) {
                const formData: SchemaForm = {
                  metadata: schemaData.metadata,
                  tables: schemaData.tables.map((table: any) => ({
                    id: table.id || `table_${Math.random()}`,
                    name: table.name || '',
                    tableType: table.type || 'entity', // Map JSON type field to form tableType
                    fields: (table.fields || table.attributes || []).map((field: any) => ({
                      name: field.name || '',
                      type: field.type || 'TEXT',
                      description: field.description || '',
                      constraints: field.constraints
                    }))
                  })),
                  relations: schemaData.relations || []
                };
                setSchemaForm(formData);
                setCurrentTableIndex(0);
              }
              else if (schemaData.table_name && schemaData.columns) {
                const formData: SchemaForm = {
                  tables: [{
                    id: 'table_1',
                    name: schemaData.table_name,
                    tableType: 'entity', // Default to entity table
                    fields: schemaData.columns.map((col: any) => ({
                      name: col.name || '',
                      type: col.type || 'TEXT',
                      description: col.description || ''
                    }))
                  }],
                  relations: []
                };
                setSchemaForm(formData);
                setCurrentTableIndex(0);
              }
            } catch (error) {
              console.error('Failed to parse history Schema data:', error);
            }
          }
          
          if (request.files && Array.isArray(request.files) && onHistoryFilesLoad) {
            const historyFiles: FileItem[] = request.files.map((filepath: string) => {
              const filename = filepath.split('/').pop() || filepath.split('\\').pop() || filepath;
              return {
                filename: filename,
                filepath: filepath,
                size: 0
              };
            });
            
            onHistoryFilesLoad(historyFiles);
          }
          
          if (request.processing_mode) {
            setProcessingMode(request.processing_mode as 'auto' | 'serial' | 'parallel');
          }
          
          if (request.document_mode) {
            setDocumentMode(request.document_mode as 'single' | 'multi');
          }
          
          if (request.model) {
            setCurrentModel(request.model);
          }
          
          if (request.max_concurrent_tables && typeof request.max_concurrent_tables === 'number') {
            setMaxConcurrentTables(request.max_concurrent_tables);
          }
        }
        
        delete (window as any).selectedHistoryTaskId;
        delete (window as any).selectedHistoryTaskDetails;
      }
    };
    
    const interval = setInterval(checkHistoryTask, 100);
    checkHistoryTask();
    
    return () => clearInterval(interval);
  }, [onHistoryFilesLoad]);

  return {
    processing,
    taskId,
    status,
    error,
    configCollapsed,
    isHistoryMode,
    historyTaskTitle,
    currentModel,
    settingsDialogOpen,
    apiKey,
    apiUrl,
    isSaving,
    saveMessage,
    memoryData,
    memoryLoading,
    inputMode,
    schemaMode,
    schemaInput,
    instructionInput,
    schemaForm,
    scrollContainerRef,
    processingMode,
    maxConcurrentTables,
    documentMode,
    
    setConfigCollapsed,
    setSettingsDialogOpen,
    setApiKey,
    setApiUrl,
    setInputMode,
    setSchemaMode,
    setSchemaInput,
    setInstructionInput,
    setSchemaForm,
    setTaskId,
    setStatus,
    setProcessing,
    setShouldKeepPolling,
    setProcessingMode,
    setMaxConcurrentTables,
    setDocumentMode,
    setIsHistoryMode,
    
    wsConnected,
    
    handleModelChange,
    handleSaveSettings,
    startProcessing,
    fetchMemoryData,
    validateFormSchema,
    validateJsonSchema,
    addColumn,
    removeColumn,
    updateColumn,
    convertFormToJson,
    convertJsonToForm,
    addTable,
    removeTable,
    updateTableName,
    updateTableType,
    addRelation,
    removeRelation,
    updateRelation,
    currentTableIndex,
    setCurrentTableIndex,
  };
};



