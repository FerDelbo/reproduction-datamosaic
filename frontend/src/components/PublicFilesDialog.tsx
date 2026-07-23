import React, { useState, useEffect } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Checkbox,
  Typography,
  CircularProgress,
  Alert,
  Box,
  Chip
} from '@mui/material';
import {
  PictureAsPdf as PictureAsPdfIcon,
  Description as DescriptionIcon,
  TableChart as TableChartIcon
} from '@mui/icons-material';

interface PublicFile {
  filepath: string;
  filename: string;
  size: number;
  type: string;
}

interface PublicFilesDialogProps {
  open: boolean;
  onClose: () => void;
  onImport: (filepaths: string[]) => Promise<void>;
}

const PublicFilesDialog: React.FC<PublicFilesDialogProps> = ({
  open,
  onClose,
  onImport
}) => {
  const [files, setFiles] = useState<PublicFile[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);

  const fetchPublicFiles = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch('/api/public-files');
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${response.status}`);
      }
      
      const data = await response.json();
      setFiles(data.files || []);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch public file list');
      console.error('Error fetching public files:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      fetchPublicFiles();
      setSelectedFiles([]);
    }
  }, [open]);

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

  const handleFileToggle = (filepath: string) => {
    setSelectedFiles(prev =>
      prev.includes(filepath)
        ? prev.filter(f => f !== filepath)
        : [...prev, filepath]
    );
  };

  const handleSelectAll = () => {
    if (selectedFiles.length === files.length) {
      setSelectedFiles([]);
    } else {
      setSelectedFiles(files.map(f => f.filepath));
    }
  };

  const handleImport = async () => {
    if (selectedFiles.length === 0) {
      setError('Please select files to import');
      return;
    }

    setImporting(true);
    setError(null);

    try {
      await onImport(selectedFiles);
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to import files');
    } finally {
      setImporting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      PaperProps={{
        sx: { height: '80vh' }
      }}
    >
      <DialogTitle>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Typography variant="h6">Import Files from Public Library</Typography>
          {files.length > 0 && (
            <Chip
              label={`${files.length} file(s) available`}
              size="small"
              color="primary"
              variant="outlined"
            />
          )}
        </Box>
      </DialogTitle>

      <DialogContent dividers>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
            <CircularProgress />
          </Box>
        ) : files.length === 0 ? (
          <Box sx={{ textAlign: 'center', p: 4, color: 'text.secondary' }}>
            <Typography variant="body2">No public files available to import</Typography>
          </Box>
        ) : (
          <>
            <Box sx={{ mb: 2 }}>
              <Button
                size="small"
                onClick={handleSelectAll}
                sx={{ mb: 1 }}
              >
                {selectedFiles.length === files.length ? 'Deselect All' : 'Select All'}
              </Button>
              {selectedFiles.length > 0 && (
                <Typography variant="body2" color="primary.main">
                  {selectedFiles.length} file(s) selected
                </Typography>
              )}
            </Box>

            <List sx={{ maxHeight: 400, overflow: 'auto' }}>
              {files.map((file, index) => {
                const isSelected = selectedFiles.includes(file.filepath);

                return (
                  <ListItem
                    key={index}
                    button
                    onClick={() => handleFileToggle(file.filepath)}
                    sx={{
                      border: '1px solid #e2e8f0',
                      borderRadius: 1,
                      mb: 1,
                      backgroundColor: isSelected ? 'rgba(25, 118, 210, 0.08)' : 'transparent',
                      '&:hover': {
                        backgroundColor: isSelected 
                          ? 'rgba(25, 118, 210, 0.12)' 
                          : 'rgba(0, 0, 0, 0.04)'
                      }
                    }}
                  >
                    <Checkbox
                      checked={isSelected}
                      tabIndex={-1}
                      disableRipple
                      size="small"
                    />

                    <ListItemIcon sx={{ minWidth: 40 }}>
                      {getFileIcon(file.filename)}
                    </ListItemIcon>

                    <ListItemText
                      primary={
                        <Typography variant="body2" sx={{ fontWeight: 500 }}>
                          {file.filename}
                        </Typography>
                      }
                      secondary={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
                          <Typography variant="caption" color="text.secondary">
                            {formatFileSize(file.size)}
                          </Typography>
                          <Chip
                            label={file.type.toUpperCase()}
                            size="small"
                            sx={{
                              height: 16,
                              fontSize: '0.65rem',
                              bgcolor: 'grey.100',
                              color: 'grey.700'
                            }}
                          />
                        </Box>
                      }
                    />
                  </ListItem>
                );
              })}
            </List>
          </>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          onClick={handleImport}
          variant="contained"
          disabled={selectedFiles.length === 0 || importing}
          startIcon={importing ? <CircularProgress size={16} /> : undefined}
        >
          {importing ? 'Importing...' : `Import (${selectedFiles.length})`}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default PublicFilesDialog;
