import React, { useState, useEffect, useRef } from 'react';
import {
  Box,
  Typography,
  Chip,
  Stack,
  CircularProgress,
  Tabs,
  Tab,
  Button
} from '@mui/material';
import {
  TableChart as TableChartIcon,
  Memory as MemoryIcon,
  Storage as StorageIcon,
  Warning as WarningIcon,
  Build as BuildIcon,
  Save as SaveIcon
} from '@mui/icons-material';
import { ProcessingStatus, MemoryData } from '../types';
import { extractAllTablesFromSnapshot } from '../utils/processingUtils';
import LargeContentViewer from '../../LargeContentViewer';
import { SnapshotsView, ViolationsView, FixesView } from './MemoryDataViews';

interface ResultsMemoryPageProps {
  status: ProcessingStatus | null;
  projectId?: string;
  memoryData: MemoryData | null;
  memoryLoading: boolean;
  taskId: string | null;
  runId?: string;
  fetchMemoryData: (runId: string) => Promise<void>;
}

const ResultsMemoryPage: React.FC<ResultsMemoryPageProps> = ({
  status,
  projectId,
  memoryData,
  memoryLoading,
  taskId,
  runId,
  fetchMemoryData
}) => {
  const [mainTab, setMainTab] = useState<number>(0);
  
  const [memorySubTab, setMemorySubTab] = useState<number>(0);
  
  const [allTables, setAllTables] = useState<Array<{tableName: string, tableData: string, rowCount: number}>>([]);
  const [loading, setLoading] = useState<boolean>(false);
  
  const prevRunIdRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    const loadTables = async () => {
      if (status) {
        setLoading(true);
        try {
          const tables = await extractAllTablesFromSnapshot(status, projectId);
          setAllTables(tables);
        } catch (error) {
          console.error('Failed to load table data:', error);
          setAllTables([]);
        } finally {
          setLoading(false);
        }
      }
    };

    loadTables();
  }, [status, projectId]);

  useEffect(() => {
    if (mainTab === 1 && !memoryLoading && runId) {
      const runIdChanged = prevRunIdRef.current !== undefined && prevRunIdRef.current !== runId;
      
      if (!memoryData || runIdChanged) {
        fetchMemoryData(runId);
      }
      
      prevRunIdRef.current = runId;
    }
  }, [mainTab, memoryData, memoryLoading, runId, fetchMemoryData]);

  const handleBatchSaveToDatabase = async () => {
    if (!projectId) {
      alert('Project ID does not exist, cannot save to database');
      return;
    }

    if (allTables.length === 0) {
      alert('No table data found to save');
      return;
    }

    try {
      const confirmed = window.confirm(
        `Are you sure you want to save ${allTables.length} tables to the database?\n\n` +
        allTables.map(t => `• ${t.tableName} (${t.rowCount} rows)`).join('\n')
      );

      if (!confirmed) return;

      const timestamp = new Date().toISOString().slice(0, 16).replace('T', '_').replace(':', '-');
      const databaseName = `doc2db_${timestamp}`;
      
      const createDbResponse = await fetch(`/api/projects/${projectId}/databases`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: databaseName,
          display_name: databaseName,
          description: `Created via Doc2DB batch import at ${new Date().toLocaleString()}`
        }),
      });

      if (!createDbResponse.ok) {
        const errorData = await createDbResponse.json();
        throw new Error(errorData.error || 'Failed to create database');
      }

      const createDbData = await createDbResponse.json();
      const databaseId = createDbData.database.id;

      const savePromises = allTables.map(async (table) => {
        const lines = table.tableData.trim().split('\n');
        if (lines.length < 3) return null;

        const headerLine = lines[0];
        const headers = headerLine.split('|').map(h => h.trim()).filter(h => h);
        const dataLines = lines.slice(2);
        
        const parsedData = dataLines.map(line => {
          const cells = line.split('|').map(c => c.trim()).filter(c => c);
          const rowData: any = {};
          headers.forEach((header, index) => {
            rowData[header] = cells[index] || '';
          });
          return rowData;
        });

        const saveResponse = await fetch(`/api/projects/${projectId}/databases/${databaseId}/tables`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            table_name: table.tableName,
            table_data: parsedData,
            merge_mode: 'create_new'
          }),
        });

        if (!saveResponse.ok) {
          const errorData = await saveResponse.json();
          throw new Error(`Failed to save table ${table.tableName}: ${errorData.error}`);
        }

        return await saveResponse.json();
      });

      await Promise.all(savePromises);

      alert(
        `Successfully saved ${allTables.length} tables to the database!\n\n` +
        `Database name: ${databaseName}\n` +
        allTables.map(t => `• ${t.tableName} (${t.rowCount} rows)`).join('\n')
      );

    } catch (error) {
      console.error('Batch save failed:', error);
      alert(`Batch save failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  return (
    <Box sx={{ 
      height: '100%', 
      display: 'flex', 
      flexDirection: 'column',
      overflow: 'hidden'
    }}>
      <Box sx={{ 
        borderBottom: 1, 
        borderColor: 'divider',
        bgcolor: 'white',
        px: 4,
        pt: 2
      }}>
        <Tabs
          value={mainTab}
          onChange={(_, newValue) => setMainTab(newValue)}
          sx={{
            '& .MuiTab-root': {
              fontSize: '0.95rem',
              fontWeight: 600,
              textTransform: 'none',
              minHeight: 56,
              px: 3
            }
          }}
        >
          <Tab 
            icon={<TableChartIcon />}
            iconPosition="start"
            label="Extraction Results" 
          />
          <Tab 
            icon={<MemoryIcon />}
            iconPosition="start"
            label="Memory Data" 
          />
        </Tabs>
      </Box>
      <Box sx={{ 
        flex: 1, 
        overflow: 'auto',
        bgcolor: '#f8fafc',
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
        {mainTab === 0 && (
          <Box sx={{ p: 4 }}>
            {loading ? (
              <Box sx={{ 
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                py: 8
              }}>
                <CircularProgress size={48} />
                <Typography sx={{ mt: 2, color: '#6b7280' }}>
                  Loading table data...
                </Typography>
              </Box>
            ) : allTables.length > 0 ? (
              <Box>
                <Box sx={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  mb: 3,
                  p: 3,
                  bgcolor: 'white',
                  borderRadius: 3,
                  boxShadow: '0 1px 3px rgba(0, 0, 0, 0.1)',
                  border: '1px solid #e2e8f0'
                }}>
                  <Box>
                    <Typography variant="h5" sx={{ fontWeight: 600, color: '#111827', mb: 1 }}>
                      📊 Extraction Results
                    </Typography>
                    <Typography variant="body2" sx={{ color: '#6b7280' }}>
                      Successfully extracted {allTables.length} tables, totaling {allTables.reduce((sum, t) => sum + t.rowCount, 0)} rows of data
                    </Typography>
                  </Box>
                  {projectId && (
                    <Button
                      variant="contained"
                      color="success"
                      startIcon={<SaveIcon />}
                      onClick={handleBatchSaveToDatabase}
                      sx={{
                        borderRadius: 2,
                        textTransform: 'none',
                        fontWeight: 600,
                        px: 3,
                        py: 1.2,
                        boxShadow: '0 4px 12px rgba(22, 163, 74, 0.3)',
                        '&:hover': {
                          boxShadow: '0 6px 16px rgba(22, 163, 74, 0.4)'
                        }
                      }}
                    >
                      Save to Database
                    </Button>
                  )}
                </Box>
                <Box sx={{ 
                  mb: 3,
                  display: 'flex', 
                  flexWrap: 'wrap', 
                  gap: 1.5
                }}>
                  {allTables.map((table, index) => (
                    <Chip
                      key={index}
                      label={`${table.tableName} (${table.rowCount} rows)`}
                      size="medium"
                      variant="outlined"
                      color="primary"
                      sx={{ 
                        fontSize: '0.85rem',
                        fontWeight: 500,
                        borderRadius: 2,
                        px: 1
                      }}
                    />
                  ))}
                </Box>
                <Stack spacing={3}>
                  {allTables.map((table, index) => (
                    <Box 
                      key={index}
                      sx={{
                        bgcolor: 'white',
                        borderRadius: 3,
                        p: 3,
                        boxShadow: '0 1px 3px rgba(0, 0, 0, 0.1)',
                        border: '1px solid #e2e8f0'
                      }}
                    >
                      <Typography variant="h6" sx={{ 
                        mb: 2.5, 
                        fontWeight: 600, 
                        color: '#111827',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 1.5
                      }}>
                        <TableChartIcon sx={{ fontSize: 24, color: '#0d6efd' }} />
                        {table.tableName}
                        <Chip 
                          label={`${table.rowCount} rows`} 
                          size="small" 
                          color="primary" 
                          variant="outlined"
                          sx={{ fontSize: '0.75rem', height: 24 }}
                        />
                      </Typography>
                      <LargeContentViewer
                        content={table.tableData}
                        contentType="table"
                        preview={table.tableData}
                        projectId={projectId}
                      />
                    </Box>
                  ))}
                </Stack>
              </Box>
            ) : (
              <Box sx={{ 
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                py: 8,
                textAlign: 'center',
                bgcolor: 'white',
                borderRadius: 3,
                mx: 4,
                my: 4,
                boxShadow: '0 1px 3px rgba(0, 0, 0, 0.1)'
              }}>
                <Box sx={{
                  width: 80,
                  height: 80,
                  borderRadius: '50%',
                  bgcolor: '#fef3c7',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  mb: 3
                }}>
                  <Typography sx={{ fontSize: '2.5rem' }}>⚠️</Typography>
                </Box>
                <Typography variant="h6" sx={{ mb: 2, fontWeight: 600, color: '#92400e' }}>
                  No extracted data found
                </Typography>
                <Typography variant="body2" sx={{ color: '#78350f', maxWidth: 500, lineHeight: 1.7 }}>
                  The system has successfully completed the processing workflow, but no valid data was extracted from the documents. Please check:
                </Typography>
                <Box sx={{ mt: 3, textAlign: 'left' }}>
                  <Typography variant="body2" sx={{ color: '#78350f', mb: 1 }}>
                    • Whether the document content is empty or the format is not supported
                  </Typography>
                  <Typography variant="body2" sx={{ color: '#78350f', mb: 1 }}>
                    • Whether the data extraction instructions are clear and explicit
                  </Typography>
                  <Typography variant="body2" sx={{ color: '#78350f', mb: 1 }}>
                    • Whether the document language matches the model
                  </Typography>
                </Box>
              </Box>
            )}
          </Box>
        )}
        {mainTab === 1 && (
          <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <Box sx={{ 
              borderBottom: 1, 
              borderColor: 'divider',
              bgcolor: 'white',
              px: 4,
              pt: 2
            }}>
              <Box sx={{ 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: 'space-between',
                mb: 2
              }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                  Run ID:
                  <Chip 
                    label={runId || taskId || 'N/A'} 
                    size="small" 
                    sx={{ fontSize: '0.7rem' }}
                  />
                </Box>
              </Box>
              
              <Tabs
                value={memorySubTab}
                onChange={(_, newValue) => setMemorySubTab(newValue)}
                sx={{
                  '& .MuiTab-root': {
                    fontSize: '0.9rem',
                    fontWeight: 500,
                    textTransform: 'none',
                    minHeight: 48
                  }
                }}
              >
                <Tab 
                  icon={<StorageIcon sx={{ fontSize: 18 }} />}
                  iconPosition="start"
                  label="Snapshots" 
                />
                <Tab 
                  icon={<WarningIcon sx={{ fontSize: 18 }} />}
                  iconPosition="start"
                  label="Violations" 
                />
                <Tab 
                  icon={<BuildIcon sx={{ fontSize: 18 }} />}
                  iconPosition="start"
                  label="Fixes" 
                />
              </Tabs>
            </Box>
            <Box sx={{ flex: 1, overflow: 'auto', p: 4 }}>
              {memoryLoading ? (
                <Box sx={{ 
                  display: 'flex', 
                  alignItems: 'center', 
                  justifyContent: 'center', 
                  height: '100%',
                  flexDirection: 'column',
                  gap: 2
                }}>
                  <CircularProgress size={48} />
                  <Typography variant="body2" sx={{ color: '#6b7280' }}>
                    Loading memory data...
                  </Typography>
                </Box>
              ) : (
                <Box>
                  {memorySubTab === 0 && (
                    <SnapshotsView snapshots={memoryData?.snapshots} />
                  )}
                  
                  {memorySubTab === 1 && (
                    <ViolationsView violations={memoryData?.violations} />
                  )}
                  
                  {memorySubTab === 2 && (
                    <FixesView fixes={memoryData?.fixes} />
                  )}
                </Box>
              )}
            </Box>
          </Box>
        )}
      </Box>
    </Box>
  );
};

export default ResultsMemoryPage;

