
export interface FileItem {
  filename: string;
  filepath: string;
  size: number;
}

export interface ColumnField {
  name: string;
  type: string;
  description: string;
  constraints?: {
    primary_key?: boolean;
    foreign_key?: boolean;
    nullable?: boolean;
    unique?: boolean;
  };
}

export interface TableSchema {
  id: string;
  name: string;
  tableType?: 'entity' | 'relation'; // Table type: entity table or relation table; defaults to entity
  fields: ColumnField[];
}

export interface TableRelation {
  id: string;
  type: 'one-to-one' | 'one-to-many' | 'many-to-one' | 'many-to-many';
  from: {
    table: string;
    field: string;
  };
  to: {
    table: string;
    field: string;
  };
}

export interface SchemaForm {
  metadata?: {
    version?: string;
    generator?: string;
    generated_at?: string;
    tables_count?: number;
    relations_count?: number;
  };
  tables: TableSchema[];
  relations?: TableRelation[];
}

export interface SingleTableForm {
  table_name: string;
  columns: ColumnField[];
}

export interface ProcessingStep {
  step_id?: string; // Unique step identifier to avoid overwriting steps with the same name
  step_name?: string;
  step?: string; // Add step property for streaming data compatibility
  description: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  start_time?: string;
  end_time?: string;
  timestamp?: string; // Add timestamp property for streaming data compatibility
  result?: any;
  details?: any; // Add details property for streaming data compatibility
  error?: string;
  llm_input?: string;
  llm_output?: string;
  llm_system_prompt?: string;
  model_used?: string;
  output_text?: string;
  document?: string;
  extracted_rows?: number;
}

export interface ProcessingStatus {
  task_id?: string; // Made optional because status updates may omit it
  status?: 'started' | 'processing' | 'completed' | 'failed';
  steps?: ProcessingStep[];
  start_time?: number;
  end_time?: number;
  error?: string;
  current_step?: string; // Add current step
  steps_count?: number; // Add step count
  result_context?: any; // Add result context
  final_stats?: any; // Add final statistics
  result?: {
    table_data: any;
    summary: any;
    run_id: string;
    snapshot?: any; // Add snapshot data
  };
}

export interface Doc2DBProcessorProps {
  selectedFiles: FileItem[];
  onClose?: () => void;
  onRemoveFile?: (filepath: string) => void;
  projectId?: string;
  onTaskCompleted?: (taskId: string) => void; // New: task completion callback that receives task ID
  onHistoryFilesLoad?: (files: FileItem[]) => void; // New: historical file load callback
}

export interface ModelOption {
  value: string;
  label: string;
  category: string;
}

export interface MemoryData {
  snapshots: any;
  violations: any;
  fixes: any;
  summary: any;
}



