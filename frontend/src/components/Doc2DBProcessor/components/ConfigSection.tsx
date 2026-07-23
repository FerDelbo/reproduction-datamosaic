import React from 'react';
import {
  Box,
  Typography,
  Button,
  IconButton,
  Chip,
  TextField,
  FormControl,
  Select,
  MenuItem,
  InputLabel,
  ToggleButtonGroup,
  ToggleButton,
  Grid,
  Stack,
  CircularProgress,
  Autocomplete
} from '@mui/material';
import {
  PlayArrow as PlayArrowIcon,
  Settings as SettingsIcon,
  AttachFile as AttachFileIcon,
  Description as DescriptionIcon,
  Close as CloseIcon,
  Add as AddIcon,
  Remove as RemoveIcon,
  Transform as TransformIcon,
  TableChart as TableChartIcon,
  Refresh as RefreshIcon
} from '@mui/icons-material';
import { FileItem, SchemaForm, ColumnField, TableSchema } from '../types';
import { MODEL_OPTIONS } from '../constants';
import { normalizeModelValue } from '../utils/processingUtils';

interface ConfigSectionProps {
  configCollapsed: boolean;
  selectedFiles: FileItem[];
  processing: boolean;
  currentModel: string;
  inputMode: 'instruction' | 'schema';
  schemaMode: 'json' | 'form';
  instructionInput: string;
  schemaInput: string;
  schemaForm: SchemaForm;
  processingMode: 'auto' | 'serial' | 'parallel';
  maxConcurrentTables: number;
  currentTableIndex: number;
  documentMode: 'single' | 'multi';
  hasCompletedTask?: boolean;
  
  validateJsonSchema: (jsonString: string) => boolean;
  validateFormSchema: () => boolean;
  
  setConfigCollapsed: (collapsed: boolean) => void;
  setInputMode: (mode: 'instruction' | 'schema') => void;
  setSchemaMode: (mode: 'json' | 'form') => void;
  setInstructionInput: (input: string) => void;
  setSchemaInput: (input: string) => void;
  setSchemaForm: (form: SchemaForm) => void;
  setProcessingMode: (mode: 'auto' | 'serial' | 'parallel') => void;
  setMaxConcurrentTables: (count: number) => void;
  setCurrentTableIndex: (index: number) => void;
  setDocumentMode: (mode: 'single' | 'multi') => void;
  
  handleModelChange: (model: string) => void;
  startProcessing: () => void;
  removeSelectedFile: (filepath: string) => void;
  addColumn: () => void;
  removeColumn: (index: number) => void;
  updateColumn: (index: number, field: keyof ColumnField, value: string) => void;
  convertFormToJson: () => void;
  convertJsonToForm: () => void;
  addTable: () => void;
  removeTable: (index: number) => void;
  updateTableName: (index: number, name: string) => void;
  updateTableType: (index: number, tableType: 'entity' | 'relation') => void;
  addRelation: () => void;
  removeRelation: (index: number) => void;
  updateRelation: (index: number, updates: Partial<any>) => void;
  onResetTask?: () => void;
}

const ConfigSection: React.FC<ConfigSectionProps> = ({
  configCollapsed,
  selectedFiles,
  processing,
  currentModel,
  inputMode,
  schemaMode,
  instructionInput,
  schemaInput,
  schemaForm,
  processingMode,
  maxConcurrentTables,
  currentTableIndex,
  documentMode,
  hasCompletedTask,
  validateJsonSchema,
  validateFormSchema,
  setConfigCollapsed,
  setInputMode,
  setSchemaMode,
  setInstructionInput,
  setSchemaInput,
  setSchemaForm,
  setProcessingMode,
  setMaxConcurrentTables,
  setCurrentTableIndex,
  setDocumentMode,
  handleModelChange,
  startProcessing,
  removeSelectedFile,
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
  onResetTask
}) => {
  const currentTable = schemaForm.tables[currentTableIndex] || schemaForm.tables[0];
  return (
    <Box sx={{ 
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden'
    }}>
      <Box sx={{ 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'flex-end',
        px: 2,
        py: 2,
        bgcolor: 'white'
      }}>
      </Box>
      <Box sx={{ 
        flex: 1,
        overflow: 'auto',
        '&::-webkit-scrollbar': {
          width: '6px',
        },
        '&::-webkit-scrollbar-track': {
          background: '#f1f5f9',
          borderRadius: '3px',
        },
        '&::-webkit-scrollbar-thumb': {
          background: '#cbd5e1',
          borderRadius: '3px',
          '&:hover': {
            background: '#94a3b8',
          },
        },
      }}>
        <Box sx={{ 
          display: 'flex', 
          gap: 4,
          alignItems: 'flex-start',
          height: '100%',
          p: 4
        }}>
          <Box sx={{ 
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            height: '100%',
            overflow: 'hidden'
          }}>
            <Box sx={{
              flex: 1,
              overflow: 'auto',
              '&::-webkit-scrollbar': {
                width: '6px',
              },
              '&::-webkit-scrollbar-track': {
                background: '#f1f5f9',
                borderRadius: '3px',
              },
              '&::-webkit-scrollbar-thumb': {
                background: '#cbd5e1',
                borderRadius: '3px',
                '&:hover': {
                  background: '#94a3b8',
                },
              },
            }}>

              <Box sx={{ 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: 'space-between', 
                mb: 3 
              }}>
                <Typography variant="h6" sx={{ fontSize: '0.95rem', fontWeight: 600, color: '#111827' }}>
                  Processing Method
                </Typography>
                <ToggleButtonGroup
                  value={inputMode}
                  exclusive
                  onChange={(_, newMode) => newMode && setInputMode(newMode)}
                  size="small"
                  sx={{
                    '& .MuiToggleButton-root': {
                      border: 'none',
                      bgcolor: '#f3f4f6',
                      color: '#6b7280',
                      borderRadius: '6px !important',
                      textTransform: 'none',
                      fontSize: '0.875rem',
                      fontWeight: 500,
                      px: 2,
                      py: 0.5,
                      '&.Mui-selected': {
                        bgcolor: '#111827',
                        color: 'white',
                        '&:hover': {
                          bgcolor: '#1f2937'
                        }
                      },
                      '&:hover': {
                        bgcolor: '#e5e7eb'
                      }
                    },
                    gap: 1
                  }}
                >
                  <ToggleButton value="instruction">
                    Description
                  </ToggleButton>
                  <ToggleButton value="schema">
                    Schema
                  </ToggleButton>
                </ToggleButtonGroup>
              </Box>
            
            {inputMode === 'instruction' ? (
              <Box>
                <TextField
                  fullWidth
                  multiline
                  rows={4}
                  placeholder="Please describe your requirements in natural language, for example:
• Extract customer name, amount, date, and item details from invoice documents
• Organize résumé information into a talent database containing name, skills, and experience
• Analyze sales reports to extract key metrics such as product name, sales volume, and revenue..."
                  value={instructionInput}
                  onChange={(e) => setInstructionInput(e.target.value)}
                  helperText="Please describe your requirements in natural language, and the AI will automatically understand and generate the corresponding data table structure"
                  sx={{
                    '& .MuiOutlinedInput-root': {
                      borderRadius: 2,
                      fontSize: '0.95rem',
                      lineHeight: 1.6,
                      bgcolor: '#f9fafb',
                      '& fieldset': {
                        borderColor: '#d1d5db'
                      },
                      '&:hover fieldset': {
                        borderColor: '#9ca3af'
                      },
                      '&.Mui-focused fieldset': {
                        borderColor: '#111827',
                        borderWidth: '1px'
                      }
                    },
                    '& .MuiFormHelperText-root': {
                      color: '#6b7280',
                      fontSize: '0.875rem',
                      mt: 1
                    }
                  }}
                />
              </Box>
            ) : (
              <Box>
                <Box sx={{ mb: 3, display: 'flex', alignItems: 'center', gap: 2 }}>
                  <ToggleButtonGroup
                    value={schemaMode}
                    exclusive
                    onChange={(_, newMode) => newMode && setSchemaMode(newMode)}
                    size="small"
                    sx={{
                      '& .MuiToggleButton-root': {
                        border: 'none',
                        bgcolor: '#f3f4f6',
                        color: '#6b7280',
                        borderRadius: '6px !important',
                        textTransform: 'none',
                        fontSize: '0.875rem',
                        fontWeight: 500,
                        px: 2,
                        py: 0.5,
                        '&.Mui-selected': {
                          bgcolor: '#111827',
                          color: 'white',
                          '&:hover': {
                            bgcolor: '#1f2937'
                          }
                        },
                        '&:hover': {
                          bgcolor: '#e5e7eb'
                        }
                      },
                      gap: 1
                    }}
                  >
                    <ToggleButton value="form">
                      Form
                    </ToggleButton>
                    <ToggleButton value="json">
                      JSON
                    </ToggleButton>
                  </ToggleButtonGroup>
                  <IconButton
                    size="small"
                    onClick={schemaMode === 'form' ? convertFormToJson : convertJsonToForm}
                    sx={{ 
                      bgcolor: '#f3f4f6',
                      color: '#6b7280',
                      '&:hover': { 
                        bgcolor: '#e5e7eb',
                        color: '#374151'
                      }
                    }}
                  >
                    <TransformIcon fontSize="small" />
                  </IconButton>
                </Box>

                {schemaMode === 'form' ? (
                  <Box>
                    <Box sx={{ mb: 3 }}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                      </Box>
                      <Box sx={{ 
                        display: 'flex', 
                        gap: 1,
                        flexWrap: 'wrap',
                        mb: 2,
                        p: 1.5,
                        bgcolor: '#f9fafb',
                        borderRadius: 2,
                        border: '1px solid #e5e7eb'
                      }}>
                        {schemaForm.tables.map((table, index) => (
                          <Chip
                            key={table.id}
                            icon={<TableChartIcon sx={{ fontSize: 14 }} />}
                            label={table.name || `Tab ${index + 1}`}
                            onClick={() => setCurrentTableIndex(index)}
                            onDelete={schemaForm.tables.length > 1 ? () => removeTable(index) : undefined}
                            variant={currentTableIndex === index ? "filled" : "outlined"}
                            color={currentTableIndex === index ? "primary" : "default"}
                            sx={{
                              fontSize: '0.75rem',
                              height: 28,
                              cursor: 'pointer',
                              bgcolor: currentTableIndex === index ? '#0d6efd' : 'white',
                              color: currentTableIndex === index ? 'white' : '#374151',
                              borderColor: currentTableIndex === index ? '#0d6efd' : '#d1d5db',
                              '&:hover': {
                                bgcolor: currentTableIndex === index ? '#0b5ed7' : '#f3f4f6'
                              },
                              '& .MuiChip-deleteIcon': {
                                color: currentTableIndex === index ? 'white' : '#6b7280',
                                '&:hover': {
                                  color: currentTableIndex === index ? '#fee' : '#ef4444'
                                }
                              }
                            }}
                          />
                        ))}
                        <IconButton
                          size="small"
                          onClick={addTable}
                          sx={{
                            width: 28,
                            height: 28,
                            bgcolor: '#10b981',
                            color: 'white',
                            '&:hover': {
                              bgcolor: '#059669'
                            }
                          }}
                        >
                          <AddIcon sx={{ fontSize: 16 }} />
                        </IconButton>
                      </Box>
                    </Box>
                    <Grid container spacing={1} sx={{ mb: 4 }}>
                      <Grid item xs={9.5}>
                        <TextField
                          fullWidth
                          size="small"
                          label="Table Name"
                          value={currentTable.name}
                          onChange={(e) => updateTableName(currentTableIndex, e.target.value)}
                          placeholder="e.g. orders, customers, products"
                          sx={{ 
                            '& .MuiOutlinedInput-root': {
                              borderRadius: 2,
                              bgcolor: '#f9fafb',
                              '& fieldset': {
                                borderColor: '#d1d5db'
                              },
                              '&:hover fieldset': {
                                borderColor: '#9ca3af'
                              },
                              '&.Mui-focused fieldset': {
                                borderColor: '#111827',
                                borderWidth: '1px'
                              }
                            }
                          }}
                        />
                      </Grid>
                      <Grid item xs={2.5}>
                        <FormControl fullWidth size="small">
                          <InputLabel sx={{ fontSize: '0.875rem' }}>Type</InputLabel>
                          <Select
                            value={currentTable.tableType || 'entity'}
                            onChange={(e) => updateTableType(currentTableIndex, e.target.value as 'entity' | 'relation')}
                            label="Type"
                            sx={{
                              bgcolor: '#f9fafb',
                              borderRadius: 2,
                              fontSize: '0.875rem',
                              '& .MuiOutlinedInput-notchedOutline': {
                                borderColor: '#d1d5db'
                              },
                              '&:hover .MuiOutlinedInput-notchedOutline': {
                                borderColor: '#9ca3af'
                              },
                              '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
                                borderColor: '#111827',
                                borderWidth: '1px'
                              }
                            }}
                          >
                            <MenuItem value="entity" sx={{ fontSize: '0.875rem' }}>Entity</MenuItem>
                            <MenuItem value="relation" sx={{ fontSize: '0.875rem' }}>Relation</MenuItem>
                          </Select>
                        </FormControl>
                      </Grid>
                    </Grid>
                    <Typography variant="body2" sx={{ mb: 2, fontWeight: 600, color: '#111827', fontSize: '0.875rem' }}>
                      Field Definition
                    </Typography>
                    <Box sx={{ 
                      border: '1px solid #e5e7eb',
                      borderRadius: 1,
                      mb: 2
                    }}>
                      {currentTable.fields.map((column, index) => (
                        <Box key={index} sx={{ 
                          p: 1.5,
                          borderBottom: index < currentTable.fields.length - 1 ? '1px solid #f3f4f6' : 'none',
                          '&:hover': {
                            bgcolor: '#f9fafb'
                          }
                        }}>
                          <Grid container spacing={1} alignItems="center">
                            <Grid item xs={3.5}>
                              <TextField
                                fullWidth
                                size="small"
                                placeholder="Field Name"
                                value={column.name}
                                onChange={(e) => updateColumn(index, 'name', e.target.value)}
                                sx={{
                                  '& .MuiOutlinedInput-root': {
                                    fontSize: '0.75rem',
                                    height: 32,
                                    '& fieldset': {
                                      borderColor: '#d1d5db'
                                    }
                                  },
                                  '& .MuiInputBase-input': {
                                    py: 1
                                  }
                                }}
                              />
                            </Grid>
                            <Grid item xs={2}>
                              <Autocomplete
                                freeSolo
                                value={column.type}
                                onChange={(event, newValue) => updateColumn(index, 'type', newValue || 'TEXT')}
                                options={[
                                  'TEXT',
                                  'VARCHAR(255)',
                                  'INT',
                                  'INTEGER',
                                  'DECIMAL(10,2)',
                                  'DATE',
                                  'DATETIME',
                                  'BOOLEAN',
                                  'ENUM',
                                  'JSON'
                                ]}
                                renderInput={(params) => (
                                  <TextField
                                    {...params}
                                    size="small"
                                    placeholder="Type"
                                    sx={{
                                      '& .MuiOutlinedInput-root': {
                                        fontSize: '0.75rem',
                                        height: 32,
                                        '& fieldset': {
                                          borderColor: '#d1d5db'
                                        }
                                      },
                                      '& .MuiInputBase-input': {
                                        py: 0.5
                                      }
                                    }}
                                  />
                                )}
                                sx={{ width: '100%' }}
                              />
                            </Grid>
                            <Grid item xs={5}>
                              <TextField
                                fullWidth
                                size="small"
                                placeholder="Field Description, Notes, Constraints etc."
                                value={column.description}
                                onChange={(e) => updateColumn(index, 'description', e.target.value)}
                                sx={{
                                  '& .MuiOutlinedInput-root': {
                                    fontSize: '0.75rem',
                                    height: 32,
                                    '& fieldset': {
                                      borderColor: '#d1d5db'
                                    }
                                  },
                                  '& .MuiInputBase-input': {
                                    py: 1
                                  }
                                }}
                              />
                            </Grid>
                            <Grid item xs={0.75}>
                              <IconButton
                                size="small"
                                onClick={() => removeColumn(index)}
                                disabled={currentTable.fields.length === 1}
                                sx={{ 
                                  width: 24,
                                  height: 24,
                                  color: '#6b7280',
                                  '&:hover': {
                                    color: '#ef4444',
                                    bgcolor: '#fef2f2'
                                  }
                                }}
                              >
                                <RemoveIcon sx={{ fontSize: 14 }} />
                              </IconButton>
                            </Grid>
                            <Grid item xs={0.75}>
                              <IconButton
                                size="small"
                                onClick={() => addColumn()}
                                sx={{ 
                                  width: 24,
                                  height: 24,
                                  color: '#6b7280',
                                  '&:hover': {
                                    color: '#10b981',
                                    bgcolor: '#ecfdf5'
                                  }
                                }}
                              >
                                <AddIcon sx={{ fontSize: 14 }} />
                              </IconButton>
                            </Grid>
                          </Grid>
                        </Box>
                      ))}
                    </Box>
                    <Box sx={{ mt: 3 }}>
                      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
                        <Typography variant="body2" sx={{ fontWeight: 600, color: '#111827', fontSize: '0.875rem' }}>
                          Relation Definition
                        </Typography>

                      </Box>
                      <Box sx={{ 
                        border: '1px solid #e5e7eb',
                        borderRadius: 1,
                        mb: 2
                      }}>
                        {(!schemaForm.relations || schemaForm.relations.length === 0) ? (
                          <Box sx={{ 
                            p: 3,
                            textAlign: 'center',
                            color: '#9ca3af',
                            fontSize: '0.8rem'
                          }}>
                            No relation definition
                          </Box>
                        ) : (
                          schemaForm.relations.map((relation, index) => (
                            <Box key={relation.id || index} sx={{ 
                              p: 2,
                              borderBottom: index < (schemaForm.relations?.length || 0) - 1 ? '1px solid #f3f4f6' : 'none',
                              '&:hover': {
                                bgcolor: '#f9fafb'
                              }
                            }}>
                              <Grid container spacing={1} alignItems="center">
                                <Grid item xs={2.5}>
                                  <FormControl fullWidth size="small">
                                    <Select
                                      value={relation.type}
                                      onChange={(e) => updateRelation(index, { type: e.target.value })}
                                      sx={{
                                        fontSize: '0.75rem',
                                        height: 32,
                                        '& fieldset': {
                                          borderColor: '#d1d5db'
                                        }
                                      }}
                                    >
                                      <MenuItem value="one-to-one" sx={{ fontSize: '0.75rem' }}>1:1</MenuItem>
                                      <MenuItem value="one-to-many" sx={{ fontSize: '0.75rem' }}>1:N</MenuItem>
                                      <MenuItem value="many-to-one" sx={{ fontSize: '0.75rem' }}>N:1</MenuItem>
                                      <MenuItem value="many-to-many" sx={{ fontSize: '0.75rem' }}>N:N</MenuItem>
                                    </Select>
                                  </FormControl>
                                </Grid>
                                <Grid item xs={2}>
                                  <FormControl fullWidth size="small">
                                    <Select
                                      value={relation.from.table}
                                      onChange={(e) => updateRelation(index, { 
                                        from: { ...relation.from, table: e.target.value }
                                      })}
                                      displayEmpty
                                      sx={{
                                        fontSize: '0.75rem',
                                        height: 32,
                                        '& fieldset': {
                                          borderColor: '#d1d5db'
                                        }
                                      }}
                                    >
                                      <MenuItem value="" disabled sx={{ fontSize: '0.75rem' }}>
                                        <em>Select Table</em>
                                      </MenuItem>
                                      {schemaForm.tables.map(table => (
                                        <MenuItem key={table.id} value={table.name} sx={{ fontSize: '0.75rem' }}>
                                          {table.name || table.id}
                                        </MenuItem>
                                      ))}
                                    </Select>
                                  </FormControl>
                                </Grid>
                                <Grid item xs={2}>
                                  <TextField
                                    fullWidth
                                    size="small"
                                    placeholder="Field"
                                    value={relation.from.field}
                                    onChange={(e) => updateRelation(index, { 
                                      from: { ...relation.from, field: e.target.value }
                                    })}
                                    sx={{
                                      '& .MuiOutlinedInput-root': {
                                        fontSize: '0.75rem',
                                        height: 32,
                                        '& fieldset': {
                                          borderColor: '#d1d5db'
                                        }
                                      },
                                      '& .MuiInputBase-input': {
                                        py: 1
                                      }
                                    }}
                                  />
                                </Grid>
                                <Grid item xs={0.5} sx={{ textAlign: 'center' }}>
                                  <Typography sx={{ fontSize: '0.75rem', color: '#6b7280' }}>→</Typography>
                                </Grid>
                                <Grid item xs={2}>
                                  <FormControl fullWidth size="small">
                                    <Select
                                      value={relation.to.table}
                                      onChange={(e) => updateRelation(index, { 
                                        to: { ...relation.to, table: e.target.value }
                                      })}
                                      displayEmpty
                                      sx={{
                                        fontSize: '0.75rem',
                                        height: 32,
                                        '& fieldset': {
                                          borderColor: '#d1d5db'
                                        }
                                      }}
                                    >
                                      <MenuItem value="" disabled sx={{ fontSize: '0.75rem' }}>
                                        <em>Select Table</em>
                                      </MenuItem>
                                      {schemaForm.tables.map(table => (
                                        <MenuItem key={table.id} value={table.name} sx={{ fontSize: '0.75rem' }}>
                                          {table.name || table.id}
                                        </MenuItem>
                                      ))}
                                    </Select>
                                  </FormControl>
                                </Grid>
                                <Grid item xs={2}>
                                  <TextField
                                    fullWidth
                                    size="small"
                                    placeholder="Field"
                                    value={relation.to.field}
                                    onChange={(e) => updateRelation(index, { 
                                      to: { ...relation.to, field: e.target.value }
                                    })}
                                    sx={{
                                      '& .MuiOutlinedInput-root': {
                                        fontSize: '0.75rem',
                                        height: 32,
                                        '& fieldset': {
                                          borderColor: '#d1d5db'
                                        }
                                      },
                                      '& .MuiInputBase-input': {
                                        py: 1
                                      }
                                    }}
                                  />
                                </Grid>
                                <Grid item xs={1}>
                                  <IconButton
                                    size="small"
                                    onClick={() => removeRelation(index)}
                                    sx={{ 
                                      width: 24,
                                      height: 24,
                                      color: '#6b7280',
                                      '&:hover': {
                                        color: '#ef4444',
                                        bgcolor: '#fef2f2'
                                      }
                                    }}
                                  >
                                    <CloseIcon sx={{ fontSize: 14 }} />
                                  </IconButton>
                                </Grid>
                              </Grid>
                            </Box>
                          ))
                        )}
                      </Box>
                      <Button
                        size="small"
                        startIcon={<AddIcon />}
                        onClick={addRelation}
                        sx={{
                          fontSize: '0.75rem',
                          textTransform: 'none',
                          color: '#6b7280',
                          '&:hover': {
                            bgcolor: '#f3f4f6',
                            color: '#374151'
                          }
                        }}
                      >
                        Add Relation
                      </Button>
                    </Box>
                  </Box>
                ) : (
                  <TextField
                    fullWidth
                    multiline
                    rows={8}
                    placeholder={`Please enter the JSON format Schema definition (supports multiple tables and relations):
{
  "metadata": {
    "version": "1.0.0",
    "tables_count": 2,
    "relations_count": 1
  },
  "tables": [
    {
      "id": "company",
      "name": "company",
      "fields": [
        {"name": "company_name", "type": "VARCHAR(255)", "description": "Company name"},
        {"name": "location", "type": "TEXT", "description": "Company address"}
      ]
    },
    {
      "id": "report",
      "name": "report",
      "fields": [
        {"name": "report_name", "type": "VARCHAR(255)", "description": "Report name"},
        {"name": "company_name", "type": "VARCHAR(255)", "description": "Parent company"},
        {"name": "year", "type": "INTEGER", "description": "Year"}
      ]
    }
  ],
  "relations": [
    {
      "id": "ref_1",
      "type": "many-to-one",
      "from": {"table": "report", "field": "company_name"},
      "to": {"table": "company", "field": "company_name"}
    }
  ]
}`}
                    value={schemaInput}
                    onChange={(e) => setSchemaInput(e.target.value)}
                    helperText="Use JSON format to precisely define the table structure and relations, supporting complex data types, constraints and foreign key relationships"
                    sx={{
                      '& .MuiInputBase-input': {
                        fontFamily: 'Fira Code, Monaco, monospace',
                        fontSize: '0.875rem',
                        lineHeight: 1.4
                      },
                      '& .MuiOutlinedInput-root': {
                        borderRadius: 2,
                        bgcolor: '#f9fafb',
                        '& fieldset': {
                          borderColor: '#d1d5db'
                        },
                        '&:hover fieldset': {
                          borderColor: '#9ca3af'
                        },
                        '&.Mui-focused fieldset': {
                          borderColor: '#111827',
                          borderWidth: '1px'
                        }
                      },
                      '& .MuiFormHelperText-root': {
                        color: '#6b7280',
                        fontSize: '0.875rem',
                        mt: 1
                      }
                    }}
                  />
                )}
              </Box>
            )}
            </Box>
          </Box>
          <Box sx={{ 
            width: 320, // Fixed width
            display: 'flex',
            flexDirection: 'column'
          }}>
            <Typography variant="h6" sx={{ fontSize: '0.95rem', fontWeight: 600, color: '#111827', mb: 2 }}>
              Choose Files
            </Typography>
            <Box sx={{ 
              display: 'flex',
              flexDirection: 'column',
              gap: 1,
              border: '1px solid #d1d5db',
              borderRadius: 2,
              bgcolor: 'white',
              height: '360px',
              transition: 'border-color 0.2s',
              '&:hover': {
                borderColor: '#9ca3af'
              },
              overflow: 'hidden'
            }}>
              <Box sx={{ 
                display: 'flex',
                alignItems: 'center',
                gap: 1,
                p: 1.5,
                borderBottom: '1px solid #e5e7eb'
              }}>
                <AttachFileIcon sx={{ fontSize: 18, color: '#6b7280' }} />
                <Typography variant="body2" sx={{ 
                  color: '#374151', 
                  fontSize: '0.8rem',
                  fontWeight: 500,
                  flex: 1
                }}>
                  {selectedFiles.length === 0 ? 'Choose Files from the left file library' : `Selected ${selectedFiles.length} files`}
                </Typography>
              </Box>
              <Box sx={{ 
                flex: 1, 
                overflow: 'auto',
                p: selectedFiles.length > 0 ? 1 : 0
              }}>
                {selectedFiles.length === 0 ? (
                  <Box sx={{ 
                    height: '100%', 
                    display: 'flex', 
                    alignItems: 'center', 
                    justifyContent: 'center',
                    color: '#9ca3af',
                    fontSize: '0.8rem'
                  }}>
                    No files selected
                  </Box>
                ) : (
                  <Stack spacing={0.5}>
                    {selectedFiles.map((file) => (
                      <Box
                        key={file.filename}
                        sx={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          p: 1,
                          borderRadius: 1,
                          '&:hover': {
                            bgcolor: '#f9fafb'
                          }
                        }}
                      >
                        <Box sx={{ 
                          display: 'flex', 
                          alignItems: 'center', 
                          gap: 1,
                          flex: 1,
                          overflow: 'hidden'
                        }}>
                          <DescriptionIcon sx={{ fontSize: 14, color: '#6b7280' }} />
                          <Typography 
                            variant="body2" 
                            sx={{ 
                              fontWeight: 500, 
                              color: '#374151',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                              fontSize: '0.75rem'
                            }}
                          >
                            {file.filename}
                          </Typography>
                        </Box>
                        <IconButton
                          size="small"
                          onClick={() => removeSelectedFile(file.filepath)}
                          sx={{ 
                            width: 20,
                            height: 20,
                            color: '#6b7280',
                            '&:hover': {
                              color: '#ef4444',
                              bgcolor: '#fef2f2'
                            }
                          }}
                        >
                          <CloseIcon sx={{ fontSize: 12 }} />
                        </IconButton>
                      </Box>
                    ))}
                  </Stack>
                )}
              </Box>
            </Box>
            <Box sx={{ mt: 3 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <Typography variant="body2" sx={{ 
                  fontSize: '0.875rem', 
                  fontWeight: 600, 
                  color: '#374151',
                  minWidth: '100px'
                }}>
                  Processing Mode
                </Typography>
                
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: 1 }}>
                  <FormControl size="small" sx={{ flex: 1 }}>
                    <Select
                      value={processingMode}
                      onChange={(e) => setProcessingMode(e.target.value as 'auto' | 'serial' | 'parallel')}
                      sx={{
                        bgcolor: 'white',
                        borderRadius: 2,
                        fontSize: '0.875rem',
                        '& .MuiOutlinedInput-notchedOutline': {
                          borderColor: '#d1d5db'
                        },
                        '&:hover .MuiOutlinedInput-notchedOutline': {
                          borderColor: '#9ca3af'
                        },
                        '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
                          borderColor: '#0d6efd'
                        }
                      }}
                    >
                      <MenuItem value="auto">
                        <Typography variant="body2" sx={{ fontSize: '0.875rem' }}>
                          Auto
                        </Typography>
                      </MenuItem>
                      <MenuItem value="serial">
                        <Typography variant="body2" sx={{ fontSize: '0.875rem' }}>
                          Serial
                        </Typography>
                      </MenuItem>
                      <MenuItem value="parallel">
                        <Typography variant="body2" sx={{ fontSize: '0.875rem' }}>
                          Parallel
                        </Typography>
                      </MenuItem>
                    </Select>
                  </FormControl>
                  {processingMode === 'parallel' && (
                    <TextField
                      type="number"
                      value={maxConcurrentTables}
                      onChange={(e) => {
                        const value = parseInt(e.target.value);
                        if (value >= 1 && value <= 10) {
                          setMaxConcurrentTables(value);
                        }
                      }}
                      inputProps={{ min: 1, max: 10 }}
                      size="small"
                      placeholder="Concurrent Number"
                      sx={{
                        width: '80px',
                        '& .MuiOutlinedInput-root': {
                          fontSize: '0.875rem',
                          height: '40px',
                          bgcolor: 'white',
                          '& fieldset': {
                            borderColor: '#d1d5db'
                          },
                          '&:hover fieldset': {
                            borderColor: '#9ca3af'
                          },
                          '&.Mui-focused fieldset': {
                            borderColor: '#0d6efd'
                          }
                        }
                      }}
                    />
                  )}
                </Box>
              </Box>
            </Box>
            <Box sx={{ mt: 3 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <Typography variant="body2" sx={{ 
                  fontSize: '0.875rem', 
                  fontWeight: 600, 
                  color: '#374151',
                  minWidth: '100px'
                }}>
                  Extract Mode
                </Typography>
                
                <FormControl size="small" sx={{ flex: 1 }}>
                  <Select
                    value={documentMode}
                    onChange={(e) => setDocumentMode(e.target.value as 'single' | 'multi')}
                    sx={{
                      bgcolor: 'white',
                      borderRadius: 2,
                      fontSize: '0.875rem',
                      '& .MuiOutlinedInput-notchedOutline': {
                        borderColor: '#d1d5db'
                      },
                      '&:hover .MuiOutlinedInput-notchedOutline': {
                        borderColor: '#9ca3af'
                      },
                      '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
                        borderColor: '#0d6efd'
                      }
                    }}
                  >
                    <MenuItem value="single">
                      <Typography variant="body2" sx={{ fontSize: '0.875rem' }}>
                        Single
                      </Typography>
                    </MenuItem>
                    <MenuItem value="multi">
                      <Typography variant="body2" sx={{ fontSize: '0.875rem' }}>
                        Combined
                      </Typography>
                    </MenuItem>
                  </Select>
                </FormControl>
              </Box>
            </Box>
            <Box sx={{ mt: 3, mb: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <Typography variant="body2" sx={{ 
                  fontSize: '0.875rem', 
                  fontWeight: 600, 
                  color: '#374151',
                  minWidth: '100px'
                }}>
                  Model
                </Typography>
                <FormControl size="small" sx={{ flex: 1 }}>
                  <Select
                    value={normalizeModelValue(currentModel)}
                    onChange={(e) => handleModelChange(e.target.value)}
                    sx={{
                      bgcolor: 'white',
                      borderRadius: 2,
                      fontSize: '0.875rem',
                      '& .MuiOutlinedInput-notchedOutline': {
                        borderColor: '#d1d5db'
                      },
                      '&:hover .MuiOutlinedInput-notchedOutline': {
                        borderColor: '#9ca3af'
                      },
                      '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
                        borderColor: '#0d6efd'
                      }
                    }}
                  >
                    {MODEL_OPTIONS.map((model) => (
                      <MenuItem key={model.value} value={model.value} sx={{ fontSize: '0.875rem' }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          {model.value === 'settings' ? (
                            <>
                              <SettingsIcon sx={{ fontSize: '0.875rem', color: '#64748b' }} />
                              <Typography variant="body2" sx={{ fontSize: '0.875rem' }}>
                                {model.label}
                              </Typography>
                            </>
                          ) : (
                            <>
                              <Typography variant="body2" sx={{ fontSize: '0.875rem' }}>
                                {model.label}
                              </Typography>
                              <Chip
                                label={model.category.toUpperCase()}
                                size="small"
                                sx={{
                                  height: '16px',
                                  fontSize: '0.625rem',
                                  backgroundColor: 
                                    model.category === 'gpt' ? '#dbeafe' :
                                    model.category === 'deepseek' ? '#dcfce7' :
                                    model.category === 'claude' ? '#fef3c7' :
                                    model.category === 'qianwen' ? '#f3e8ff' : '#f1f5f9',
                                  color:
                                    model.category === 'gpt' ? '#1d4ed8' :
                                    model.category === 'deepseek' ? '#166534' :
                                    model.category === 'claude' ? '#92400e' :
                                    model.category === 'qianwen' ? '#7c3aed' : '#475569',
                                }}
                              />
                            </>
                          )}
                        </Box>
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Box>
            </Box>
            <Box sx={{ mt: 2 }}>
              {!processing && (
                <Button
                  variant="contained"
                  fullWidth
                  startIcon={hasCompletedTask ? <RefreshIcon /> : <PlayArrowIcon />}
                  onClick={() => {
                    if (hasCompletedTask && onResetTask) {
                      onResetTask();
                    } else {
                      startProcessing();
                    }
                  }}
                  disabled={
                    selectedFiles.length === 0 || 
                    (inputMode === 'instruction' && !instructionInput.trim()) ||
                    (inputMode === 'schema' && schemaMode === 'json' && !validateJsonSchema(schemaInput)) ||
                    (inputMode === 'schema' && schemaMode === 'form' && !validateFormSchema())
                  }
                  sx={{ 
                    py: 1.5,
                    borderRadius: 2,
                    fontSize: '0.95rem',
                    fontWeight: 600,
                    bgcolor: hasCompletedTask ? '#6c757d' : '#0d6efd',
                    color: 'white',
                    textTransform: 'none',
                    boxShadow: hasCompletedTask 
                      ? '0 4px 12px rgba(108, 117, 125, 0.4)'
                      : '0 4px 12px rgba(13, 110, 253, 0.4)',
                    '&:hover': {
                      bgcolor: hasCompletedTask ? '#5a6268' : '#0b5ed7',
                      transform: 'translateY(-2px)',
                      boxShadow: hasCompletedTask
                        ? '0 6px 20px rgba(108, 117, 125, 0.5)'
                        : '0 6px 20px rgba(13, 110, 253, 0.5)'
                    },
                    '&:disabled': {
                      bgcolor: '#e9ecef',
                      color: '#adb5bd',
                      boxShadow: 'none'
                    },
                    transition: 'all 0.3s ease'
                  }}
                >
                  {hasCompletedTask ? 'Re-analyze' : 'Begin Analysis'}
                </Button>
              )}
              
              {processing && (
                <Button
                  variant="contained"
                  fullWidth
                  startIcon={<CircularProgress size={20} />}
                  disabled
                  sx={{
                    py: 1.5,
                    borderRadius: 2,
                    fontSize: '0.9rem',
                    fontWeight: 600,
                    textTransform: 'none',
                    bgcolor: '#f8f9fa',
                    color: '#6c757d',
                    border: '1px solid #dee2e6'
                  }}
                >
                  Analyzing...
                </Button>
              )}
            </Box>
          </Box>
        </Box>
      </Box>
    </Box>
  );
};

export default ConfigSection;
