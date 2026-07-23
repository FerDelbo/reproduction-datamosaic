import React, { useState, useEffect, useRef } from 'react';
import {
  CircularProgress,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Menu,
  MenuItem
} from '@mui/material';
import {
  TableChart as TableChartIcon,
  Delete as DeleteIcon,
  Add as AddIcon,
  Edit as EditIcon,
  MoreVert as MoreVertIcon
} from '@mui/icons-material';
import '../styles/ChatHistoryPanel.css';
import { resolveDisplayTableName } from './Doc2DBProcessor/utils/processingUtils';

interface Doc2DBRecord {
  id: string;
  title: string;
  status: 'started' | 'processing' | 'completed' | 'failed';
  start_time: string;
  end_time?: string;
  total_rows: number;
  table_name: string;
  schema?: string;
  violations_count: number;
  fixes_count: number;
}

interface Doc2DBHistoryPanelProps {
  onSelectRecord?: (recordId: string) => void;
  onNewSession?: () => void;
  onDeleteRecord?: (recordId: string) => void;
  currentRecordId?: string | null;
  refreshTrigger?: number;
  projectId?: string;
}

const Doc2DBHistoryPanel: React.FC<Doc2DBHistoryPanelProps> = ({
  onSelectRecord,
  onNewSession,
  onDeleteRecord,
  currentRecordId,
  refreshTrigger = 0,
  projectId
}) => {
  const [records, setRecords] = useState<Doc2DBRecord[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  const [isRenaming, setIsRenaming] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState('');
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [recordToDelete, setRecordToDelete] = useState<string | null>(null);
  const [isSelectingRecord, setIsSelectingRecord] = useState<string | null>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);



  const fetchHistory = async () => {
    setIsLoading(true);
    setError(null);
    
    try {
      const url = projectId ? `/api/projects/${projectId}/doc2db/history` : '/api/doc2db/history';
      const response = await fetch(url);
      
      if (response.ok) {
        const data = await response.json();
        setRecords(data || []);
      } else {
        const errorData = await response.json();
        setError(errorData.error || 'Failed to fetch processing history');
      }
    } catch (err) {
      console.error('Failed to fetch processing history:', err);
      setError('Network connection failed');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectRecord = (recordId: string) => {
    if (isRenaming !== recordId) {
      setIsSelectingRecord(recordId);
      onSelectRecord?.(recordId);
      handleCloseMenu();
      
      setTimeout(() => {
        setIsSelectingRecord(null);
      }, 500);
    }
  };

  const handleMenuClick = (event: React.MouseEvent<HTMLElement>, recordId: string) => {
    event.stopPropagation();
    setAnchorEl(event.currentTarget);
    setSelectedRecordId(recordId);
  };

  const handleCloseMenu = () => {
    setAnchorEl(null);
    setSelectedRecordId(null);
  };

  const handleRename = () => {
    if (selectedRecordId) {
      const record = records.find(r => r.id === selectedRecordId);
      if (record) {
        setIsRenaming(selectedRecordId);
        setNewTitle(record.table_name || '');
      }
    }
    handleCloseMenu();
  };

  const handleRenameSubmit = async (recordId: string) => {
    if (!newTitle.trim()) {
      setIsRenaming(null);
      return;
    }

    try {
      const url = projectId 
        ? `/api/projects/${projectId}/doc2db/history/${recordId}/rename`
        : `/api/doc2db/history/${recordId}/rename`;
      
      const response = await fetch(url, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ title: newTitle.trim() }),
      });
      
      if (response.ok) {
        setRecords(prev => 
          prev.map(record => 
            record.id === recordId 
              ? { ...record, table_name: newTitle.trim() }
              : record
          )
        );
        
        setIsRenaming(null);
        setNewTitle('');
      } else {
        const errorData = await response.json();
        setError(errorData.error || 'Rename failed');
      }
    } catch (err) {
      console.error('Rename failed:', err);
      setError('Rename failed');
    }
  };

  const handleRenameKeyDown = (e: React.KeyboardEvent, recordId: string) => {
    if (e.key === 'Enter') {
      handleRenameSubmit(recordId);
    } else if (e.key === 'Escape') {
      setIsRenaming(null);
      setNewTitle('');
    }
  };

  const handleDeleteConfirm = () => {
    if (selectedRecordId) {
      setRecordToDelete(selectedRecordId);
      setDeleteDialogOpen(true);
    }
    handleCloseMenu();
  };

  const handleDelete = async () => {
    if (!recordToDelete) return;

    try {
      const url = projectId 
        ? `/api/projects/${projectId}/doc2db/history/${recordToDelete}/delete`
        : `/api/doc2db/history/${recordToDelete}/delete`;
      
      const response = await fetch(url, { method: 'DELETE' });
      
      if (response.ok) {
        setRecords(prev => prev.filter(record => record.id !== recordToDelete));
        
        if (onDeleteRecord) {
          onDeleteRecord(recordToDelete);
        }
        
        setDeleteDialogOpen(false);
        setRecordToDelete(null);
      } else {
        const errorData = await response.json();
        setError(errorData.error || 'Delete record failed');
      }
    } catch (err) {
      console.error('Delete record failed:', err);
      setError('Delete record failed');
    }
  };

  useEffect(() => {
    fetchHistory();
  }, [refreshTrigger, projectId]);

  useEffect(() => {
    if (isRenaming && renameInputRef.current) {
      renameInputRef.current.focus();
    }
  }, [isRenaming]);

  const formatDateTime = (dateTimeStr: string) => {
    const date = new Date(dateTimeStr);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
  };

  return (
    <div className="chat-history-panel-content">
      <div className="chat-history-actions">
        <button 
          className="new-chat-button"
          onClick={onNewSession}
          title="New Task"
        >
          <AddIcon style={{ fontSize: 14 }} />
          New Task
        </button>
      </div>

      <div className="chat-history-list">
        {isLoading ? (
          <div className="history-loading">
            <CircularProgress size={16} />
            Loading...
          </div>
        ) : error ? (
          <div className="history-error">
            {error}
            <Button 
              onClick={fetchHistory} 
              size="small" 
              sx={{ mt: 1, display: 'block', margin: '8px auto 0' }}
            >
              Retry
            </Button>
          </div>
        ) : records.length === 0 ? (
          <div className="empty-history-message">
            <TableChartIcon className="empty-state-icon" />
            <div className="empty-message-text">
              <div>No task history</div>
              <div>Start the first Doc2DB processing task to view history records</div>
            </div>
          </div>
        ) : (
          records.map((record) => (
            <div
              key={record.id}
              className={`chat-history-item ${record.id === currentRecordId ? 'active' : ''} ${isSelectingRecord === record.id ? 'selecting' : ''}`}
              onClick={() => handleSelectRecord(record.id)}
            >
              <div className="chat-history-item-content">
                {isRenaming === record.id ? (
                  <input
                    ref={renameInputRef}
                    type="text"
                    className="rename-input"
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    onKeyDown={(e) => handleRenameKeyDown(e, record.id)}
                    onBlur={() => handleRenameSubmit(record.id)}
                    onClick={(e) => e.stopPropagation()}
                    placeholder="Enter new title..."
                  />
                ) : (
                  <>
                    <div className="chat-history-item-title">
                      {resolveDisplayTableName(record.table_name, record.schema)}
                      <span style={{
                        marginLeft: '8px',
                        padding: '2px 6px',
                        borderRadius: '3px',
                        fontSize: '10px',
                        backgroundColor: 
                          record.status === 'completed' ? '#f0f9ff' :
                          record.status === 'failed' ? '#fef2f2' :
                          record.status === 'processing' ? '#fff7ed' : '#f3f4f6',
                        color:
                          record.status === 'completed' ? '#1e40af' :
                          record.status === 'failed' ? '#dc2626' :
                          record.status === 'processing' ? '#ea580c' : '#6b7280'
                      }}>
                        {record.status === 'completed' ? 'Completed' :
                         record.status === 'failed' ? 'Failed' :
                         record.status === 'processing' ? 'Processing' : 'Pending'}
                      </span>
                    </div>
                    <div style={{ fontSize: '11px', color: '#8c8c8c', marginTop: '2px' }}>
                      {formatDateTime(record.start_time)}
                    </div>
                  </>
                )}
              </div>
              {!isRenaming && (
                <div className="chat-history-item-options">
                  <button
                    className="options-button"
                    onClick={(e) => handleMenuClick(e, record.id)}
                    title="More options"
                  >
                    <MoreVertIcon style={{ fontSize: 16 }} />
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={handleCloseMenu}
        anchorOrigin={{
          vertical: 'bottom',
          horizontal: 'right',
        }}
        transformOrigin={{
          vertical: 'top',
          horizontal: 'right',
        }}
        PaperProps={{
          className: 'options-menu',
          sx: {
            mt: 1,
            borderRadius: '6px',
            minWidth: 120,
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
          }
        }}
      >
        <MenuItem 
          onClick={handleRename}
          sx={{ 
            fontSize: '14px',
            py: '8px',
            px: '16px',
            minHeight: 'auto',
            color: '#262626'
          }}
        >
          <EditIcon style={{ fontSize: 16, marginRight: 8, color: '#8c8c8c' }} />
          Rename
        </MenuItem>
        <MenuItem 
          onClick={handleDeleteConfirm} 
          className="delete-option"
          sx={{ 
            color: '#ff4d4f',
            fontSize: '14px',
            py: '8px',
            px: '16px',
            minHeight: 'auto'
          }}
        >
          <DeleteIcon style={{ fontSize: 16, marginRight: 8 }} />
          Delete
        </MenuItem>
      </Menu>

      <Dialog
        open={deleteDialogOpen}
        onClose={() => setDeleteDialogOpen(false)}
        aria-labelledby="delete-dialog-title"
        className="delete-dialog"
        PaperProps={{
          sx: {
            borderRadius: '8px',
            minWidth: 320
          }
        }}
      >
        <DialogTitle 
          id="delete-dialog-title"
          sx={{ 
            fontSize: '16px',
            fontWeight: 500,
            color: '#262626',
            padding: '20px 24px 8px'
          }}
        >
          Confirm delete task
        </DialogTitle>
        <DialogContent sx={{ padding: '8px 24px 20px' }}>
          <div style={{ fontSize: '14px', color: '#595959' }}>
            Are you sure you want to delete this task record? This action cannot be undone.
          </div>
        </DialogContent>
        <DialogActions sx={{ padding: '12px 16px 16px', gap: '8px' }}>
          <Button 
            onClick={() => setDeleteDialogOpen(false)}
            sx={{ 
              textTransform: 'none',
              fontWeight: 400,
              minWidth: 64,
              height: 32,
              padding: '4px 15px',
              fontSize: '14px',
              borderRadius: '6px',
              color: '#595959'
            }}
          >
            Cancel
          </Button>
          <Button 
            onClick={handleDelete} 
            variant="contained"
            sx={{ 
              textTransform: 'none',
              fontWeight: 400,
              minWidth: 64,
              height: 32,
              padding: '4px 15px',
              fontSize: '14px',
              borderRadius: '6px',
              backgroundColor: '#ff4d4f',
              boxShadow: 'none',
              '&:hover': {
                backgroundColor: '#ff7875',
                boxShadow: 'none'
              }
            }}
          >
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
};

export default Doc2DBHistoryPanel;
