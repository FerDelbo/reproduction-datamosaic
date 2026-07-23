import React, { useState, useEffect } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import CircularProgress from '@mui/material/CircularProgress';
import ErrorIcon from '@mui/icons-material/Error';
import Paper from '@mui/material/Paper';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import RefreshIcon from '@mui/icons-material/Refresh';
import { alpha } from '@mui/material/styles';

interface FileContentViewerProps {
  filepath: string;
  projectId?: string;
}

interface FileContent {
  content: string;
  filename: string;
  file_type: string;
  error?: string;
}

const FileContentViewer: React.FC<FileContentViewerProps> = ({ 
  filepath, 
  projectId = 'default-project' 
}) => {
  const [fileContent, setFileContent] = useState<FileContent | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchFileContent = async (filePath: string) => {
    setLoading(true);
    setError(null);
    
    try {
      const apiUrl = projectId && projectId !== 'default-project' 
        ? `/api/projects/${projectId}/files/content`
        : `/api/files/content`;
        
      const url = new URL(apiUrl, window.location.origin);
      url.searchParams.set('filepath', filePath);
      
      const response = await fetch(url.toString(), {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        }
      });
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      
      setFileContent({
        content: data.content || '',
        filename: data.filename || filePath.split('/').pop() || 'Unknown File',
        file_type: data.file_type || 'unknown'
      });
    } catch (err: any) {
      const errorMessage = err.message || 'Failed to read file';
      setError(errorMessage);
      setFileContent(null);
      console.error('File content fetch error:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (filepath) {
      fetchFileContent(filepath);
    } else {
      setFileContent(null);
      setError(null);
    }
  }, [filepath, projectId]);

  const handleRetry = () => {
    if (filepath) {
      fetchFileContent(filepath);
    }
  };

  const getFileTypeInfo = (fileType: string) => {
    switch (fileType.toLowerCase()) {
      case 'pdf':
        return { label: 'PDF', color: '#dc2626' };
      case 'txt':
        return { label: 'TXT', color: '#059669' };
      case 'md':
      case 'markdown':
        return { label: 'Markdown', color: '#7c3aed' };
      case 'csv':
        return { label: 'CSV', color: '#ea580c' };
      case 'xlsx':
      case 'xls':
        return { label: 'Excel', color: '#16a34a' };
      case 'docx':
        return { label: 'Word', color: '#2563eb' };
      default:
        return { label: fileType.toUpperCase() || 'Unknown', color: '#6b7280' };
    }
  };

  const formatContent = (content: string, fileType: string) => {
    if (fileType.toLowerCase() === 'md' || fileType.toLowerCase() === 'markdown') {
      return content;
    }
    
    return content;
  };

  if (!filepath) {
    return (
      <Box sx={{ 
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        p: 3,
        color: 'text.secondary'
      }}>
        <Typography variant="h6" sx={{ mb: 2, fontWeight: 500 }}>
        Document Reader
        </Typography>
        <Typography variant="body2" align="center" sx={{ opacity: 0.7 }}>
        Please select a file to view its content
        </Typography>
      </Box>
    );
  }

  if (loading) {
    return (
      <Box sx={{ 
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        p: 3
      }}>
        <CircularProgress size={40} sx={{ mb: 2 }} />
        <Typography variant="body2" color="text.secondary">
        Loading file content...
        </Typography>
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ 
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        p: 3
      }}>
        <ErrorIcon sx={{ fontSize: 48, color: 'error.main', mb: 2 }} />
        <Typography variant="h6" color="error.main" sx={{ mb: 1 }}>
        Read failed
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2, textAlign: 'center' }}>
          {error}
        </Typography>
        <IconButton 
          onClick={handleRetry} 
          color="primary"
          sx={{ 
            bgcolor: alpha('#2563eb', 0.1),
            '&:hover': { bgcolor: alpha('#2563eb', 0.2) }
          }}
        >
          <RefreshIcon />
        </IconButton>
      </Box>
    );
  }

  if (!fileContent) {
    return (
      <Box sx={{ 
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        p: 3
      }}>
        <Typography variant="body2" color="text.secondary">
        No content
        </Typography>
      </Box>
    );
  }

  const fileTypeInfo = getFileTypeInfo(fileContent.file_type);

  return (
    <Box sx={{ 
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden'
    }}>
      <Box sx={{ 
        p: 2,
        borderBottom: '1px solid #e2e8f0',
        bgcolor: '#f8fafc'
      }}>
        <Box sx={{ 
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          mb: 1
        }}>
          <Typography variant="subtitle2" sx={{ 
            fontWeight: 600,
            fontSize: '0.875rem',
            color: 'text.primary',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            flex: 1,
            mr: 1
          }}>
            {fileContent.filename}
          </Typography>
          
          <Chip
            label={fileTypeInfo.label}
            size="small"
            sx={{
              bgcolor: alpha(fileTypeInfo.color, 0.1),
              color: fileTypeInfo.color,
              fontSize: '0.7rem',
              height: 20,
              '& .MuiChip-label': {
                px: 1
              }
            }}
          />
        </Box>
        
        <Typography variant="caption" sx={{ 
          color: 'text.secondary',
          fontSize: '0.75rem'
        }}>
          {filepath}
        </Typography>
      </Box>

      <Box sx={{ 
        flex: 1,
        overflow: 'auto',
        bgcolor: '#ffffff'
      }}>
        <Paper 
          elevation={0} 
          sx={{ 
            height: '100%',
            borderRadius: 0,
            border: 'none',
            bgcolor: 'transparent'
          }}
        >
          <Box sx={{ 
            p: 3,
            height: '100%',
            overflow: 'auto',
            fontFamily: 'monospace',
            fontSize: '0.875rem',
            lineHeight: 1.6,
            color: 'text.primary',
            backgroundColor: '#ffffff',
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
            {fileContent.content ? (
              <pre style={{ 
                margin: 0,
                whiteSpace: 'pre-wrap',
                wordWrap: 'break-word',
                fontFamily: 'inherit',
                fontSize: 'inherit',
                lineHeight: 'inherit'
              }}>
                {formatContent(fileContent.content, fileContent.file_type)}
              </pre>
            ) : (
              <Box sx={{ 
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '200px',
                color: 'text.secondary'
              }}>
                <Typography variant="body2">
                File content is empty
                </Typography>
              </Box>
            )}
          </Box>
        </Paper>
      </Box>
    </Box>
  );
};

export default FileContentViewer;
