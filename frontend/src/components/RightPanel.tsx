/**
 * Right panel component
 */
import React from 'react';
import {
  Box,
  Typography,
  IconButton,
  Tooltip
} from '@mui/material';
import {
  ChevronRight as ChevronRightIcon,
  Description as DescriptionIcon
} from '@mui/icons-material';

import FileContentViewer from './FileContentViewer';

interface RightPanelProps {
  isRightPanelCollapsed: boolean;
  rightPanelWidth: number;
  isResizing: boolean;
  selectedFileForReading: string | null;
  projectId: string;
  
  setIsRightPanelCollapsed: (collapsed: boolean) => void;
  handleMouseDown: (e: React.MouseEvent) => void;
}

const RightPanel: React.FC<RightPanelProps> = ({
  isRightPanelCollapsed,
  rightPanelWidth,
  isResizing,
  selectedFileForReading,
  projectId,
  setIsRightPanelCollapsed,
  handleMouseDown,
}) => {
  return (
    <Box sx={{ 
      width: isRightPanelCollapsed ? '60px' : `${rightPanelWidth}px`,
      transition: isResizing ? 'none' : 'width 0.3s ease-in-out',
      backgroundColor: '#f8fafc',
      borderLeft: '1px solid #e2e8f0',
      display: 'flex',
      flexDirection: 'column',
      boxShadow: isRightPanelCollapsed ? 'none' : '-2px 0 8px rgba(0,0,0,0.1)',
      zIndex: 10,
      position: 'relative'
    }}>
      {isRightPanelCollapsed ? (
        <Box sx={{ 
          display: 'flex', 
          flexDirection: 'column',
          alignItems: 'center',
          height: '100%',
          pt: 2,
          gap: 1
        }}>
          <Tooltip title="Document Reader" placement="left">
            <IconButton 
              onClick={() => setIsRightPanelCollapsed(false)}
              sx={{ 
                bgcolor: 'grey.300',
                color: 'grey.600',
                height: '30px',
                width: '30px',
                '&:hover': { bgcolor: 'grey.400' }
              }}
            >
              <DescriptionIcon sx={{ fontSize: '15px' }} />
            </IconButton>
          </Tooltip>
        </Box>
      ) : (
        <>
          <Box
            onMouseDown={handleMouseDown}
            sx={{
              position: 'absolute',
              left: 0,
              top: 0,
              bottom: 0,
              width: '4px',
              cursor: 'col-resize',
              backgroundColor: 'transparent',
              zIndex: 20,
              '&:hover': {
                backgroundColor: 'primary.main',
                opacity: 0.5
              },
              '&:active': {
                backgroundColor: 'primary.dark',
                opacity: 0.7
              }
            }}
          />
          <Box sx={{ 
            display: 'flex', 
            flexDirection: 'column',
            height: '100%',
            p: 3
          }}>
          <Box sx={{ 
            display: 'flex', 
            alignItems: 'center', 
            justifyContent: 'space-between',
            mb: 2,
            pb: 1,
            borderBottom: '1px solid #e2e8f0'
          }}>
            <Typography variant="h6" sx={{ 
              fontSize: '1rem', 
              fontWeight: 600,
              color: 'text.primary'
            }}>
              Document Reader
            </Typography>
            
            <Tooltip title="Collapse Panel" placement="bottom">
              <IconButton 
                onClick={() => setIsRightPanelCollapsed(true)}
                size="small"
                sx={{ 
                  color: 'text.secondary',
                  '&:hover': { bgcolor: 'action.hover' }
                }}
              >
                <ChevronRightIcon />
              </IconButton>
            </Tooltip>
          </Box>
          
            <Box sx={{ flexGrow: 1, overflow: 'hidden' }}>
              <FileContentViewer 
                filepath={selectedFileForReading || ''} 
                projectId={projectId} 
              />
            </Box>
          </Box>
        </>
      )}
    </Box>
  );
};

export default RightPanel;
