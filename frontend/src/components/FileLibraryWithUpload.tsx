import React, { useState, useRef, useEffect, useMemo } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
import PublicIcon from '@mui/icons-material/Public';
import CircularProgress from '@mui/material/CircularProgress';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemText from '@mui/material/ListItemText';
import ListItemIcon from '@mui/material/ListItemIcon';
import PictureAsPdfIcon from '@mui/icons-material/PictureAsPdf';
import DescriptionIcon from '@mui/icons-material/Description';
import TableChartIcon from '@mui/icons-material/TableChart';
import DeleteIcon from '@mui/icons-material/Delete';
import RefreshIcon from '@mui/icons-material/Refresh';
import AddIcon from '@mui/icons-material/Add';
import IconButton from '@mui/material/IconButton';
import Checkbox from '@mui/material/Checkbox';
import '../styles/ChatHistoryPanel.css';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import { styled } from '@mui/material/styles';
import Paper from '@mui/material/Paper';
import { alpha } from '@mui/material/styles';
import VisibilityIcon from '@mui/icons-material/Visibility';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';

interface FileItem {
  filename: string;
  filepath: string;
  size: number;
}

interface FileLibraryWithUploadProps {
  files: FileItem[];
  selectable?: boolean;
  onFileSelect?: (filepath: string) => void;
  selectedFiles?: string[];
  onFileUpload?: (files: File[]) => void;
  onDeleteFile?: (filepath: string) => void;
  onRefreshFiles?: () => void;
  onSelectAll?: () => void;
  onFileRead?: (filepath: string) => void;
  onNewChat?: () => void;
  isUploading?: boolean;
  isRefreshing?: boolean;
  onPublicFileImport?: () => void;
  projectId?: string;
}

const UploadArea = styled(Box)(({ theme, isDragOver }: { theme?: any; isDragOver: boolean }) => ({
  border: `2px dashed ${isDragOver ? theme?.palette?.primary?.main || '#2563eb' : '#e2e8f0'}`,
  borderRadius: theme?.shape?.borderRadius || 8,
  padding: theme?.spacing ? theme.spacing(3) : '24px',
  textAlign: 'center',
  backgroundColor: isDragOver ? alpha('#2563eb', 0.05) : 'transparent',
  cursor: 'pointer',
  transition: 'all 0.2s ease-in-out',
  '&:hover': {
    borderColor: theme?.palette?.primary?.main || '#2563eb',
    backgroundColor: alpha('#2563eb', 0.02),
  },
}));

const FileLibraryWithUpload: React.FC<FileLibraryWithUploadProps> = ({
  files,
  selectable = false,
  onFileSelect,
  selectedFiles = [],
  onFileUpload,
  onDeleteFile,
  onRefreshFiles,
  onSelectAll,
  onFileRead,
  onNewChat,
  isUploading = false,
  isRefreshing = false,
  onPublicFileImport,
  projectId
}) => {
  const [isDragOver, setIsDragOver] = useState(false);
  const [contextMenu, setContextMenu] = useState<{
    mouseX: number;
    mouseY: number;
    filepath: string;
  } | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [fileToDelete, setFileToDelete] = useState<{ filepath: string; filename: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const sortedFiles = useMemo(() => {
    return [...files].sort((a, b) => a.filename.localeCompare(b.filename));
  }, [files]);

  const getFileIcon = (filename: string) => {
    const extension = filename.split('.').pop()?.toLowerCase() || '';
    switch (extension) {
      case 'pdf':
        return <PictureAsPdfIcon sx={{ color: '#dc2626' }} />;
      case 'csv':
      case 'xlsx':
      case 'xls':
        return <TableChartIcon sx={{ color: '#059669' }} />;
      case 'txt':
      case 'md':
      case 'docx':
      default:
        return <DescriptionIcon sx={{ color: '#2563eb' }} />;
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  useEffect(() => {
    const handleWindowDragEnter = (e: DragEvent) => {
      e.preventDefault();
      setIsDragOver(true);
    };

    const handleWindowDragOver = (e: DragEvent) => {
      e.preventDefault();
    };

    const handleWindowDrop = (e: DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
    };

    window.addEventListener('dragenter', handleWindowDragEnter);
    window.addEventListener('dragover', handleWindowDragOver);
    window.addEventListener('drop', handleWindowDrop);

    return () => {
      window.removeEventListener('dragenter', handleWindowDragEnter);
      window.removeEventListener('dragover', handleWindowDragOver);
      window.removeEventListener('drop', handleWindowDrop);
    };
  }, []);

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.currentTarget.contains(e.relatedTarget as Node)) {
      return;
    }
    setIsDragOver(false);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true); // Keep state true while dragging
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    const droppedFiles = Array.from(e.dataTransfer.files);
    if (droppedFiles.length > 0 && onFileUpload) {
      onFileUpload(droppedFiles);
      setTimeout(() => {
        setIsDragOver(false);
      }, 300);
    } else {
      setIsDragOver(false);
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(e.target.files || []);
    if (selectedFiles.length > 0 && onFileUpload) {
      onFileUpload(selectedFiles);
    }
    e.target.value = '';
  };

  const handleFolderInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(e.target.files || []);
    if (selectedFiles.length > 0 && onFileUpload) {
      onFileUpload(selectedFiles);
    }
    e.target.value = '';
  };

  const handleContextMenu = (event: React.MouseEvent, filepath: string) => {
    event.preventDefault();
    setContextMenu(
      contextMenu === null
        ? {
            mouseX: event.clientX + 2,
            mouseY: event.clientY - 6,
            filepath
          }
        : null,
    );
  };

  const handleCloseContextMenu = () => {
    setContextMenu(null);
  };

  const handleDeleteClick = (filepath: string, filename: string) => {
    setFileToDelete({ filepath, filename });
    setDeleteDialogOpen(true);
  };

  const handleConfirmDelete = () => {
    if (fileToDelete && onDeleteFile) {
      onDeleteFile(fileToDelete.filepath);
    }
    setDeleteDialogOpen(false);
    setFileToDelete(null);
  };

  const handleCancelDelete = () => {
    setDeleteDialogOpen(false);
    setFileToDelete(null);
  };

  const handleDeleteFromContext = () => {
    if (contextMenu) {
      const file = files.find(f => f.filepath === contextMenu.filepath);
      if (file) {
        handleDeleteClick(file.filepath, file.filename);
      }
    }
    handleCloseContextMenu();
  };

  const handleReadFromContext = () => {
    if (contextMenu && onFileRead) {
      onFileRead(contextMenu.filepath);
    }
    handleCloseContextMenu();
  };

  return (
    <Box sx={{ 
      height: '100%', 
      display: 'flex', 
      flexDirection: 'column',
      overflow: 'hidden'
    }}>
      <div className="chat-history-actions">
        <button 
          className="new-chat-button"
          onClick={onNewChat}
          title="New Task"
        >
          <AddIcon style={{ fontSize: 14 }} />
          New Task
        </button>
      </div>
      <UploadArea
        isDragOver={isDragOver}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        sx={{ mb: 2 }}
      >
        {isUploading ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <CircularProgress size={24} sx={{ mb: 1 }} />
            <Typography variant="body2" color="text.secondary">
              Uploading...
            </Typography>
          </Box>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <CloudUploadIcon sx={{ fontSize: 32, color: 'primary.main', mb: 1 }} />
            <Typography variant="body2" color="text.primary" sx={{ fontWeight: 500 }}>
              Click or drag and drop to upload files
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Supports PDF, TXT, MD, CSV, XLSX, DOCX formats
            </Typography>
          </Box>
        )}
      </UploadArea>
      <Box sx={{ 
        display: 'flex', 
        gap: 1, 
        mb: 2,
        justifyContent: 'space-between'
      }}>
        <Box sx={{ display: 'flex', gap: 1, flex: 1 }}>
          <Button
            startIcon={<CloudUploadIcon />}
            onClick={() => fileInputRef.current?.click()}
            size="small"
            variant="outlined"
            sx={{ 
              flex: 1,
              fontSize: '0.75rem',
              py: 0.5
            }}
          >
            Select File
          </Button>
          <Button
            startIcon={<FolderOpenIcon />}
            onClick={() => folderInputRef.current?.click()}
            size="small"
            variant="outlined"
            sx={{ 
              flex: 1,
              fontSize: '0.75rem',
              py: 0.5
            }}
          >
            Select Folder
          </Button>
        </Box>
        
        {onPublicFileImport && (
          <Button
            startIcon={<PublicIcon />}
            onClick={onPublicFileImport}
            size="small"
            variant="outlined"
            sx={{ 
              fontSize: '0.75rem',
              py: 0.5,
              minWidth: 'auto'
            }}
          >
            Public
          </Button>
        )}
      </Box>
      {files.length > 0 && (
        <Box sx={{ 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'space-between',
          mb: 1
        }}>
          <Typography variant="subtitle2" sx={{ 
            fontSize: '0.875rem',
            fontWeight: 600,
            color: 'text.primary'
          }}>
            File List ({files.length})
          </Typography>
          
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            {selectable && onSelectAll && (
              <Button
                onClick={onSelectAll}
                size="small"
                variant="text"
                sx={{ 
                  fontSize: '0.7rem',
                  minWidth: 'auto',
                  px: 1,
                  py: 0.25
                }}
              >
                {selectedFiles.length === files.length ? 'Cancel All' : 'Select All'}
              </Button>
            )}
            
            {onRefreshFiles && (
              <IconButton
                onClick={onRefreshFiles}
                size="small"
                disabled={isRefreshing}
                sx={{ 
                  color: 'text.secondary',
                  '&:hover': { color: 'primary.main' }
                }}
              >
                <RefreshIcon sx={{ fontSize: 16 }} />
              </IconButton>
            )}
          </Box>
        </Box>
      )}
      <Box sx={{ 
        flexGrow: 1, 
        overflowY: 'auto',
        '&::-webkit-scrollbar': {
          width: '4px',
        },
        '&::-webkit-scrollbar-track': {
          background: '#f1f5f9',
          borderRadius: '2px',
        },
        '&::-webkit-scrollbar-thumb': {
          background: '#cbd5e1',
          borderRadius: '2px',
          '&:hover': {
            background: '#94a3b8',
          },
        },
      }}>
        {files.length === 0 ? (
          <Box sx={{ 
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            height: 200,
            color: 'text.secondary'
          }}>
            <DescriptionIcon sx={{ fontSize: 48, mb: 2, opacity: 0.5 }} />
            <Typography variant="body2" align="center">
              No uploaded files
            </Typography>
            <Typography variant="caption" align="center" sx={{ mt: 1, opacity: 0.7 }}>
              Drag files to the upload area above
            </Typography>
          </Box>
        ) : (
          <List sx={{ p: 0 }}>
            {sortedFiles.map((file, index) => {
              const isSelected = selectedFiles.includes(file.filepath);
              
              return (
                <ListItem
                  key={`${file.filepath}-${index}`}
                  sx={{
                    px: 1,
                    py: 0.5,
                    borderRadius: 1,
                    mb: 0.5,
                    cursor: selectable ? 'pointer' : 'default',
                    backgroundColor: isSelected ? alpha('#2563eb', 0.1) : 'transparent',
                    border: isSelected ? `1px solid ${alpha('#2563eb', 0.3)}` : '1px solid transparent',
                    '&:hover': {
                      backgroundColor: alpha('#2563eb', 0.05),
                    },
                  }}
                  onClick={() => {
                    if (selectable && onFileSelect) {
                      onFileSelect(file.filepath);
                    }
                  }}
                  onContextMenu={(e) => handleContextMenu(e, file.filepath)}
                >
                  {selectable && (
                    <Checkbox
                      checked={isSelected}
                      onChange={() => {
                        if (onFileSelect) {
                          onFileSelect(file.filepath);
                        }
                      }}
                      size="small"
                      sx={{ 
                        p: 0.5,
                        mr: 1,
                        '& .MuiSvgIcon-root': { fontSize: 16 }
                      }}
                    />
                  )}
                  
                  <ListItemIcon sx={{ minWidth: 28 }}>
                    {getFileIcon(file.filename)}
                  </ListItemIcon>
                  
                  <ListItemText
                    primary={
                      <Typography 
                        variant="body2" 
                        sx={{ 
                          fontSize: '0.8rem',
                          fontWeight: 500,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap'
                        }}
                        title={file.filename}
                      >
                        {file.filename}
                      </Typography>
                    }
                    secondary={
                      <Typography 
                        variant="caption" 
                        sx={{ 
                          fontSize: '0.7rem',
                          color: 'text.secondary'
                        }}
                      >
                        {formatFileSize(file.size)}
                      </Typography>
                    }
                    sx={{ m: 0 }}
                  />
                  
                  <Box sx={{ 
                    display: 'flex', 
                    alignItems: 'center',
                    opacity: 0.7,
                    '&:hover': { opacity: 1 }
                  }}>
                    {onFileRead && (
                      <IconButton
                        size="small"
                        onClick={(e) => {
                          e.stopPropagation();
                          onFileRead(file.filepath);
                        }}
                        sx={{ 
                          p: 0.25,
                          mr: 0.5,
                          color: 'primary.main',
                          '&:hover': { bgcolor: alpha('#2563eb', 0.1) }
                        }}
                      >
                        <VisibilityIcon sx={{ fontSize: 14 }} />
                      </IconButton>
                    )}
                    
                    {onDeleteFile && (
                      <IconButton
                        size="small"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteClick(file.filepath, file.filename);
                        }}
                        sx={{ 
                          p: 0.25,
                          color: 'error.main',
                          '&:hover': { bgcolor: alpha('#dc2626', 0.1) }
                        }}
                      >
                        <DeleteIcon sx={{ fontSize: 14 }} />
                      </IconButton>
                    )}
                  </Box>
                </ListItem>
              );
            })}
          </List>
        )}
      </Box>
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".pdf,.txt,.md,.csv,.xlsx,.xls,.docx"
        style={{ display: 'none' }}
        onChange={handleFileInputChange}
      />
      
      <input
        ref={folderInputRef}
        type="file"
        // @ts-ignore
        webkitdirectory=""
        multiple
        style={{ display: 'none' }}
        onChange={handleFolderInputChange}
      />
      <Menu
        open={contextMenu !== null}
        onClose={handleCloseContextMenu}
        anchorReference="anchorPosition"
        anchorPosition={
          contextMenu !== null
            ? { top: contextMenu.mouseY, left: contextMenu.mouseX }
            : undefined
        }
      >
        {onFileRead && (
          <MenuItem onClick={handleReadFromContext}>
            <DescriptionIcon sx={{ mr: 1, fontSize: 16 }} />
            Read Document
          </MenuItem>
        )}
        {onDeleteFile && (
          <MenuItem onClick={handleDeleteFromContext}>
            <DeleteIcon sx={{ mr: 1, fontSize: 16 }} />
            Delete File
          </MenuItem>
        )}
      </Menu>
      <Dialog
        open={deleteDialogOpen}
        onClose={handleCancelDelete}
        maxWidth="sm"
        fullWidth
      >
          <DialogTitle>Confirm Delete File</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete file "{fileToDelete?.filename}"?
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            This action cannot be undone, and the file will be permanently deleted.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCancelDelete}>
            Cancel
          </Button>
          <Button 
            onClick={handleConfirmDelete} 
            variant="contained"
            color="error"
          >
            Confirm Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default FileLibraryWithUpload;
