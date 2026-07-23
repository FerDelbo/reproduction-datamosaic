import React from 'react';
import {
  Box,
  Button,
  CircularProgress
} from '@mui/material';
import {
  Visibility as VisibilityIcon,
  Memory as MemoryIcon,
  Refresh as RefreshIcon
} from '@mui/icons-material';
import { ProcessingStatus } from '../types';

interface ActionButtonsProps {
  status: ProcessingStatus | null;
  processing: boolean;
  onViewResult: () => void;
  onOpenMemory: () => void;
  onReset: () => void;
}

const ActionButtons: React.FC<ActionButtonsProps> = ({
  status,
  processing,
  onViewResult,
  onOpenMemory,
  onReset
}) => {
  if (processing) {
    return (
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
    );
  }

  if (status?.status === 'completed') {
    return (
      <Box sx={{ display: 'flex', gap: 2, flexDirection: 'column' }}>
        <Button
          variant="contained"
          fullWidth
          startIcon={<VisibilityIcon />}
          onClick={onViewResult}
          sx={{
            py: 1.5,
            borderRadius: 2,
            fontSize: '0.95rem',
            fontWeight: 600,
            textTransform: 'none',
            bgcolor: status?.result_context?.summary?.total_rows > 0 ? '#198754' : '#f59e0b',
            boxShadow: status?.result_context?.summary?.total_rows > 0 
              ? '0 4px 12px rgba(25, 135, 84, 0.4)' 
              : '0 4px 12px rgba(245, 158, 11, 0.4)',
            '&:hover': {
              bgcolor: status?.result_context?.summary?.total_rows > 0 ? '#146c43' : '#d97706',
              transform: 'translateY(-1px)'
            }
          }}
        >
          {status?.result_context?.summary?.total_rows > 0 
            ? `View Result`
            : 'View Report'
          }
        </Button>
        <Button
          variant="outlined"
          fullWidth
          startIcon={<MemoryIcon />}
          onClick={onOpenMemory}
          sx={{
            py: 1.2,
            borderRadius: 2,
            fontSize: '0.9rem',
            fontWeight: 600,
            textTransform: 'none',
            borderColor: '#6366f1',
            color: '#6366f1',
            '&:hover': {
              borderColor: '#4f46e5',
              bgcolor: '#f8faff',
              transform: 'translateY(-1px)'
            }
          }}
        >
          🧠 Memory Data
        </Button>
        
        <Button
          variant="outlined"
          fullWidth
          startIcon={<RefreshIcon />}
          onClick={onReset}
          sx={{
            py: 1.5,
            borderRadius: 2,
            fontSize: '0.95rem',
            fontWeight: 600,
            textTransform: 'none',
            borderColor: '#dee2e6',
            color: '#6c757d',
            '&:hover': {
              borderColor: '#adb5bd',
              bgcolor: '#f8f9fa'
            }
          }}
        >
          Re-analyze
        </Button>
      </Box>
    );
  }

  return null;
};

export default ActionButtons;



