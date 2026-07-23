import React, { useState, useEffect } from 'react';
import {
  Box, Typography, Paper, Button, Dialog, DialogTitle, DialogContent,
  DialogActions, TextField, List, ListItem, ListItemText, ListItemSecondaryAction,
  IconButton, Tabs, Tab, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, TablePagination, Chip, Alert, CircularProgress,
  Card, CardContent, CardActions, Grid, Divider
} from '@mui/material';
import {
  Add as AddIcon, Storage as StorageIcon, TableChart as TableIcon,
  Code as CodeIcon, Delete as DeleteIcon, Edit as EditIcon,
  Refresh as RefreshIcon, Download as DownloadIcon, Save as SaveIcon,
  GetApp as ExportIcon
} from '@mui/icons-material';

interface Database {
  id: string;
  name: string;
  description: string;
  created_at: string;
  last_modified: string;
  tables: { name: string; row_count: number }[];
  file_size: number;
}

interface Table {
  name: string;
  columns: { name: string; type: string; not_null: boolean; primary_key: boolean }[];
  row_count: number;
}

interface TableData {
  data: any[];
  columns: { name: string; type: string }[];
  pagination: {
    page: number;
    page_size: number;
    total_count: number;
    total_pages: number;
  };
}

interface DatabaseManagerProps {
  projectId: string;
}

const DatabaseManager: React.FC<DatabaseManagerProps> = ({ projectId }) => {
  const [databases, setDatabases] = useState<Database[]>([]);
  const [selectedDatabase, setSelectedDatabase] = useState<string | null>(null);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [tables, setTables] = useState<Table[]>([]);
  const [tableData, setTableData] = useState<TableData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tabValue, setTabValue] = useState(0);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);
  
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [newDatabaseName, setNewDatabaseName] = useState('');
  const [newDatabaseDescription, setNewDatabaseDescription] = useState('');

  const fetchDatabases = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`/api/projects/${projectId}/databases`);
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${response.status}`);
      }
      
      const data = await response.json();
      setDatabases(data.databases || []);
    } catch (err: any) {
      setError(err.message || 'Get database list failed');
      console.error('Error fetching databases:', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchTables = async (databaseId: string) => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`/api/projects/${projectId}/databases/${databaseId}/tables`);
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${response.status}`);
      }
      
      const data = await response.json();
      setTables(data.tables || []);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch table list');
      console.error('Error fetching tables:', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchTableData = async (databaseId: string, tableName: string, page: number = 0, pageSize: number = 25) => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(
        `/api/projects/${projectId}/databases/${databaseId}/tables/${tableName}/data?page=${page + 1}&page_size=${pageSize}`
      );
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${response.status}`);
      }
      
      const data = await response.json();
      setTableData(data);
    } catch (err: any) {
      setError(err.message || 'Get table data failed');
      console.error('Error fetching table data:', err);
    } finally {
      setLoading(false);
    }
  };

  const createDatabase = async () => {
    if (!newDatabaseName.trim()) {
      setError('Database name cannot be empty');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`/api/projects/${projectId}/databases`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: newDatabaseName.trim(),
          description: newDatabaseDescription.trim() || undefined
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${response.status}`);
      }

      setCreateDialogOpen(false);
      setNewDatabaseName('');
      setNewDatabaseDescription('');

      await fetchDatabases();
    } catch (err: any) {
      setError(err.message || 'Create database failed');
      console.error('Error creating database:', err);
    } finally {
      setLoading(false);
    }
  };

  const deleteDatabase = async (databaseId: string) => {
    if (!window.confirm('Are you sure you want to delete this database? This action is irreversible.')) {
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`/api/projects/${projectId}/databases/${databaseId}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${response.status}`);
      }

      if (selectedDatabase === databaseId) {
        setSelectedDatabase(null);
        setSelectedTable(null);
        setTables([]);
        setTableData(null);
      }

      await fetchDatabases();
    } catch (err: any) {
      setError(err.message || 'Delete database failed');
      console.error('Error deleting database:', err);
    } finally {
      setLoading(false);
    }
  };

  const exportDatabase = async (databaseId: string, databaseName: string) => {
    try {
      const response = await fetch(`/api/projects/${projectId}/databases/${databaseId}/export`);
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${response.status}`);
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${databaseName}.db`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err: any) {
      setError(err.message || 'Failed to export database');
      console.error('Error exporting database:', err);
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const formatDate = (dateString: string): string => {
    return new Date(dateString).toLocaleString('zh-CN');
  };

  const handleDatabaseSelect = (databaseId: string) => {
    setSelectedDatabase(databaseId);
    setSelectedTable(null);
    setTableData(null);
    setTabValue(0);
    fetchTables(databaseId);
  };

  const handleTableSelect = (tableName: string) => {
    setSelectedTable(tableName);
    setTabValue(1);
    setPage(0);
    if (selectedDatabase) {
      fetchTableData(selectedDatabase, tableName, 0, rowsPerPage);
    }
  };

  const handleChangePage = (event: unknown, newPage: number) => {
    setPage(newPage);
    if (selectedDatabase && selectedTable) {
      fetchTableData(selectedDatabase, selectedTable, newPage, rowsPerPage);
    }
  };

  const handleChangeRowsPerPage = (event: React.ChangeEvent<HTMLInputElement>) => {
    const newRowsPerPage = parseInt(event.target.value, 10);
    setRowsPerPage(newRowsPerPage);
    setPage(0);
    if (selectedDatabase && selectedTable) {
      fetchTableData(selectedDatabase, selectedTable, 0, newRowsPerPage);
    }
  };

  useEffect(() => {
    fetchDatabases();
  }, [projectId]);

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Box sx={{ 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'space-between',
        p: 2,
        borderBottom: '1px solid #e2e8f0'
      }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography variant="h6" sx={{ fontWeight: 600 }}>
          </Typography>
        </Box>
        
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button
            startIcon={<AddIcon />}
            variant="contained"
            size="small"
            onClick={() => setCreateDialogOpen(true)}
            sx={{ fontSize: '0.875rem' }}
          >
            New Database
          </Button>
          <Button
            startIcon={<RefreshIcon />}
            variant="outlined"
            size="small"
            onClick={fetchDatabases}
            disabled={loading}
            sx={{ fontSize: '0.875rem' }}
          >
            Refresh
          </Button>
        </Box>
      </Box>
      {error && (
        <Alert 
          severity="error" 
          sx={{ m: 2, mb: 0 }} 
          onClose={() => setError(null)}
        >
          {error}
        </Alert>
      )}
      <Box sx={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        <Paper sx={{ 
          width: 300, 
          display: 'flex', 
          flexDirection: 'column',
          borderRadius: 0,
          borderRight: '1px solid #e2e8f0'
        }}>
          <Box sx={{ p: 2, borderBottom: '1px solid #e2e8f0' }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
              Database List ({databases.length})
            </Typography>
          </Box>
          
          <Box sx={{ flex: 1, overflow: 'auto' }}>
            {loading && databases.length === 0 ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
                <CircularProgress size={24} />
              </Box>
            ) : databases.length === 0 ? (
              <Box sx={{ p: 3, textAlign: 'center', color: 'text.secondary' }}>
                <StorageIcon sx={{ fontSize: 48, mb: 1, opacity: 0.5 }} />
                <Typography variant="body2">No database</Typography>
                <Typography variant="caption" sx={{ opacity: 0.7 }}>
                  Click the button above to create a new database
                </Typography>
              </Box>
            ) : (
              <List sx={{ p: 0 }}>
                {databases.map((db) => (
                  <ListItem
                    key={db.id}
                    button
                    selected={selectedDatabase === db.id}
                    onClick={() => handleDatabaseSelect(db.id)}
                    sx={{
                      borderBottom: '1px solid #f0f2f5',
                      '&.Mui-selected': {
                        bgcolor: 'primary.50',
                        borderRight: '3px solid',
                        borderRightColor: 'primary.main'
                      }
                    }}
                  >
                    <ListItemText
                      primary={
                        <Typography variant="body2" sx={{ fontWeight: 500 }}>
                          {db.name}
                        </Typography>
                      }
                      secondary={
                        <Box>
                          <Typography variant="caption" color="text.secondary">
                            {db.description || 'No description'}
                          </Typography>
                          <Box sx={{ display: 'flex', gap: 1, mt: 0.5 }}>
                            <Chip 
                              label={`${db.tables.length} tables`}
                              size="small"
                              sx={{ height: 16, fontSize: '0.7rem' }}
                            />
                            <Chip 
                              label={formatFileSize(db.file_size)}
                              size="small" 
                              sx={{ height: 16, fontSize: '0.7rem' }}
                            />
                          </Box>
                        </Box>
                      }
                    />
                    <ListItemSecondaryAction>
                      <IconButton
                        size="small"
                        onClick={(e) => {
                          e.stopPropagation();
                          exportDatabase(db.id, db.name);
                        }}
                        sx={{ mr: 0.5 }}
                      >
                        <ExportIcon fontSize="small" />
                      </IconButton>
                      <IconButton
                        size="small"
                        color="error"
                        onClick={(e) => {
                          e.stopPropagation();
                          deleteDatabase(db.id);
                        }}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </ListItemSecondaryAction>
                  </ListItem>
                ))}
              </List>
            )}
          </Box>
        </Paper>
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {selectedDatabase ? (
            <>
              <Tabs 
                value={tabValue} 
                onChange={(e, newValue) => setTabValue(newValue)}
                sx={{ borderBottom: '1px solid #e2e8f0' }}
              >
                <Tab label="Table Structure" />
                <Tab label="Data View" disabled={!selectedTable} />
              </Tabs>
              <Box sx={{ flex: 1, overflow: 'hidden' }}>
                {tabValue === 0 && (
                  <Box sx={{ height: '100%', overflow: 'auto', p: 2 }}>
                    <Typography variant="h6" sx={{ mb: 2 }}>
                      Tables ({tables.length})
                    </Typography>
                    
                    {loading ? (
                      <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
                        <CircularProgress />
                      </Box>
                    ) : tables.length === 0 ? (
                      <Box sx={{ textAlign: 'center', p: 4, color: 'text.secondary' }}>
                        <TableIcon sx={{ fontSize: 48, mb: 1, opacity: 0.5 }} />
                        <Typography variant="body2">No tables in the database</Typography>
                      </Box>
                    ) : (
                      <Grid container spacing={2}>
                        {tables.map((table) => (
                          <Grid item xs={12} sm={6} md={4} key={table.name}>
                            <Card 
                              sx={{ 
                                cursor: 'pointer',
                                '&:hover': { boxShadow: 2 },
                                border: selectedTable === table.name ? '2px solid' : '1px solid',
                                borderColor: selectedTable === table.name ? 'primary.main' : 'grey.300'
                              }}
                              onClick={() => handleTableSelect(table.name)}
                            >
                              <CardContent sx={{ pb: 1 }}>
                                <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                                  <TableIcon sx={{ mr: 1, color: 'primary.main' }} />
                                  <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                                    {table.name}
                                  </Typography>
                                </Box>
                                
                                <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
                                  <Chip 
                                    label={`${table.columns.length} columns`}
                                    size="small"
                                    color="primary"
                                    variant="outlined"
                                  />
                                  <Chip 
                                    label={`${table.row_count} rows`}
                                    size="small"
                                    color="secondary"
                                    variant="outlined"
                                  />
                                </Box>
                                
                                <Typography variant="caption" color="text.secondary">
                                  Fields: {table.columns.map(col => col.name).join(', ')}
                                </Typography>
                              </CardContent>
                            </Card>
                          </Grid>
                        ))}
                      </Grid>
                    )}
                  </Box>
                )}

                {tabValue === 1 && selectedTable && (
                  <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                    <Box sx={{ p: 2, borderBottom: '1px solid #e2e8f0' }}>
                      <Typography variant="h6">
                        {selectedTable} - Data View
                      </Typography>
                    </Box>
                    
                    <Box sx={{ flex: 1, overflow: 'auto' }}>
                      {loading ? (
                        <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
                          <CircularProgress />
                        </Box>
                      ) : tableData && tableData.data.length > 0 ? (
                        <>
                          <TableContainer>
                            <Table size="small" stickyHeader>
                              <TableHead>
                                <TableRow>
                                  {tableData.columns.map((column) => (
                                    <TableCell 
                                      key={column.name}
                                      sx={{ 
                                        fontWeight: 600,
                                        bgcolor: 'grey.50',
                                        minWidth: 120
                                      }}
                                    >
                                      {column.name}
                                      <Typography 
                                        variant="caption" 
                                        sx={{ 
                                          display: 'block',
                                          color: 'text.secondary',
                                          fontWeight: 400
                                        }}
                                      >
                                        {column.type}
                                      </Typography>
                                    </TableCell>
                                  ))}
                                </TableRow>
                              </TableHead>
                              <TableBody>
                                {tableData.data.map((row, index) => (
                                  <TableRow key={index} hover>
                                    {tableData.columns.map((column) => (
                                      <TableCell key={column.name}>
                                        {row[column.name] !== null && row[column.name] !== undefined
                                          ? String(row[column.name])
                                          : <em style={{ color: '#999' }}>NULL</em>
                                        }
                                      </TableCell>
                                    ))}
                                  </TableRow>
                                ))}
                              </TableBody>
                            </Table>
                          </TableContainer>
                          
                          <TablePagination
                            rowsPerPageOptions={[10, 25, 50, 100]}
                            component="div"
                            count={tableData.pagination.total_count}
                            rowsPerPage={rowsPerPage}
                            page={page}
                            onPageChange={handleChangePage}
                            onRowsPerPageChange={handleChangeRowsPerPage}
                          />
                        </>
                      ) : (
                        <Box sx={{ textAlign: 'center', p: 4, color: 'text.secondary' }}>
                          <Typography variant="body2">No data in the table</Typography>
                        </Box>
                      )}
                    </Box>
                  </Box>
                )}
              </Box>
            </>
          ) : (
            <Box sx={{ 
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              color: 'text.secondary'
            }}>
              <StorageIcon sx={{ fontSize: 64, mb: 2, opacity: 0.5 }} />
              <Typography variant="h6" sx={{ mb: 1 }}>
                Please select a database
              </Typography>
              <Typography variant="body2">
                Select a database from the left list
              </Typography>
            </Box>
          )}
        </Box>
      </Box>
      <Dialog
        open={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Create New Database</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="Database Name"
            fullWidth
            variant="outlined"
            value={newDatabaseName}
            onChange={(e) => setNewDatabaseName(e.target.value)}
            sx={{ mb: 2 }}
          />
          <TextField
            margin="dense"
            label="Description (Optional)"
            fullWidth
            multiline
            rows={3}
            variant="outlined"
            value={newDatabaseDescription}
            onChange={(e) => setNewDatabaseDescription(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateDialogOpen(false)}>
            Cancel
          </Button>
          <Button 
            onClick={createDatabase} 
            variant="contained"
            disabled={!newDatabaseName.trim() || loading}
          >
            Create
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default DatabaseManager;
