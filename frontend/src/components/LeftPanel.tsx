/**
 * Left panel component
 */
import React from 'react';
import {
  Box,
  IconButton,
  Tooltip,
  ToggleButton,
  ToggleButtonGroup
} from '@mui/material';
import {
  ChevronLeft as ChevronLeftIcon,
  Storage as StorageIcon,
  CloudUpload as CloudUploadIcon,
  History as HistoryIcon,
  Add as AddIcon
} from '@mui/icons-material';

import FileLibraryWithUpload from './FileLibraryWithUpload';
import Doc2DBHistoryPanel from './Doc2DBHistoryPanel';
import { FileItem } from '../constants/config';

interface LeftPanelProps {
  isLeftPanelCollapsed: boolean;
  leftPanelType: 'files' | 'history' | 'database';
  files: FileItem[];
  selectedFiles: FileItem[];
  selectedFilePaths: string[];
  isLoading: boolean;
  projectId: string;
  currentRecordId: string | null;
  historyRefreshTrigger: number;
  
  setLeftPanelType: (type: 'files' | 'history' | 'database') => void;
  setIsLeftPanelCollapsed: (collapsed: boolean) => void;
  
  onFileSelect: (filepath: string) => void;
  onFileUpload: (files: File[]) => Promise<void>;
  onDeleteFile: (filepath: string) => Promise<void>;
  onRefreshFiles: () => Promise<void>;
  onSelectAll: () => void;
  onFileRead: (filepath: string) => void;
  
  onNewSession: () => void;
  onSelectRecord: (taskId: string) => Promise<void>;
  onDeleteRecord: (taskId: string) => void;
  onOpenDatabaseManager: () => void;
}

const LeftPanel: React.FC<LeftPanelProps> = ({
  isLeftPanelCollapsed,
  leftPanelType,
  files,
  selectedFiles,
  selectedFilePaths,
  isLoading,
  projectId,
  currentRecordId,
  historyRefreshTrigger,
  setLeftPanelType,
  setIsLeftPanelCollapsed,
  onFileSelect,
  onFileUpload,
  onDeleteFile,
  onRefreshFiles,
  onSelectAll,
  onFileRead,
  onNewSession,
  onSelectRecord,
  onDeleteRecord,
  onOpenDatabaseManager,
}) => {
  return (
    <Box sx={{ 
      width: isLeftPanelCollapsed ? '60px' : '360px',
      transition: 'width 0.3s ease-in-out',
      backgroundColor: '#ffffff',
      borderRight: '1px solid #e2e8f0',
      display: 'flex',
      flexDirection: 'column',
      boxShadow: isLeftPanelCollapsed ? 'none' : '2px 0 8px rgba(0,0,0,0.1)',
      zIndex: 10
    }}>
      {isLeftPanelCollapsed ? (
        <Box sx={{ 
          display: 'flex', 
          flexDirection: 'column',
          alignItems: 'center',
          height: '100%',
          pt: 2,
          gap: 1
        }}>
          <Tooltip title="Doc" placement="right">
            <IconButton 
              onClick={() => {
                setLeftPanelType('files');
                setIsLeftPanelCollapsed(false);
              }}
              sx={{ 
                bgcolor: 'grey.300',
                color: 'grey.600',
                height: '30px',
                width: '30px',
                '&:hover': { 
                  bgcolor: 'grey.400' 
                }
              }}
            >
              <CloudUploadIcon sx={{ fontSize: '15px' }} />
            </IconButton>
          </Tooltip>
          
          <Tooltip title="Task" placement="right">
            <IconButton 
              onClick={() => {
                setLeftPanelType('history');
                setIsLeftPanelCollapsed(false);
              }}
              sx={{ 
                bgcolor: 'grey.300',
                color: 'grey.600',
                height: '30px',
                width: '30px',
                '&:hover': { 
                  bgcolor: 'grey.400' 
                }
              }}
            >
              <HistoryIcon sx={{ fontSize: '15px' }} />
            </IconButton>
          </Tooltip>
          
          <Tooltip title="Database" placement="right">
            <IconButton 
              onClick={onOpenDatabaseManager}
              sx={{ 
                bgcolor: 'grey.300',
                color: 'grey.600',
                height: '30px',
                width: '30px',
                '&:hover': { 
                  bgcolor: 'grey.400' 
                }
              }}
            >
              <StorageIcon sx={{ fontSize: '15px' }} />
            </IconButton>
          </Tooltip>
          
          <Tooltip title="New Task" placement="right">
            <IconButton 
              onClick={onNewSession}
              sx={{ 
                bgcolor: '#000000',
                color: '#ffffff',
                height: '30px',
                width: '30px',
                '&:hover': { 
                  bgcolor: '#333333' 
                }
              }}
            >
              <AddIcon sx={{ fontSize: '15px' }} />
            </IconButton>
          </Tooltip>
        </Box>
      ) : (
        <Box sx={{ 
          display: 'flex', 
          flexDirection: 'column',
          height: '100%',
          p: 2,
          pt: 4
        }}>
          <Box sx={{ 
            display: 'flex', 
            justifyContent: 'space-between', 
            alignItems: 'center',
            mb: 2
          }}>
            <ToggleButtonGroup
              value={leftPanelType}
              exclusive
              onChange={(event, newType) => {
                if (newType !== null) {
                  if (newType === 'database') {
                    onOpenDatabaseManager();
                  } else {
                    setLeftPanelType(newType);
                  }
                }
              }}
              size="small"
              sx={{
                '& .MuiToggleButton-root': {
                  px: 1.5,
                  py: 0.5,
                  fontSize: '0.75rem',
                  minWidth: 'auto',
                  color: '#64748b',
                  '&.Mui-selected': {
                    backgroundColor: '#2563eb',
                    color: '#ffffff',
                    '&:hover': {
                      backgroundColor: '#1d4ed8',
                    }
                  }
                }
              }}
            >
              <ToggleButton value="files">
                <CloudUploadIcon sx={{ fontSize: '14px', mr: 0.5 }} />
                Doc
              </ToggleButton>
              <ToggleButton value="history">
                <HistoryIcon sx={{ fontSize: '14px', mr: 0.5 }} />
                Task
              </ToggleButton>
              <ToggleButton value="database">
                <StorageIcon sx={{ fontSize: '14px', mr: 0.5 }} />
                Database
              </ToggleButton>
            </ToggleButtonGroup>
            
            <Tooltip title="Collapse Panel" placement="bottom">
              <IconButton 
                onClick={() => setIsLeftPanelCollapsed(true)}
                size="small"
                sx={{ 
                  bgcolor: 'transparent',
                  color: '#000000',
                  height: '28px',
                  width: '28px',
                  '&:hover': { 
                    bgcolor: 'rgba(0, 0, 0, 0.04)'
                  }
                }}
              >
                <ChevronLeftIcon sx={{ fontSize: '14px' }} />
              </IconButton>
            </Tooltip>
          </Box>
          
          <Box sx={{ flexGrow: 1, overflow: 'hidden' }}>
            {leftPanelType === 'files' ? (
              <FileLibraryWithUpload
                files={files}
                selectable={true}
                onFileSelect={onFileSelect}
                selectedFiles={selectedFilePaths}
                onFileUpload={onFileUpload}
                onDeleteFile={onDeleteFile}
                onRefreshFiles={onRefreshFiles}
                onSelectAll={onSelectAll}
                onFileRead={onFileRead}
                onNewChat={onNewSession}
                isUploading={isLoading}
                isRefreshing={isLoading}
                projectId={projectId}
              />
            ) : leftPanelType === 'history' ? (
              <Doc2DBHistoryPanel
                onSelectRecord={onSelectRecord}
                onNewSession={onNewSession}
                onDeleteRecord={onDeleteRecord}
                currentRecordId={currentRecordId}
                refreshTrigger={historyRefreshTrigger}
                projectId={projectId}
              />
            ) : null}
          </Box>
        </Box>
      )}
    </Box>
  );
};

export default LeftPanel;
