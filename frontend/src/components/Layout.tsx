/**
 * Main layout component
 */
import React, { useEffect } from 'react';
import {
  Container,
  Box,
  Paper,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button
} from '@mui/material';

import LeftPanel from './LeftPanel';
import RightPanel from './RightPanel';
import Doc2DBProcessor from './Doc2DBProcessor';
import DatabaseManager from './DatabaseManager';

import { FileItem } from '../constants/config';

interface LayoutProps {
  files: FileItem[];
  selectedFiles: FileItem[];
  selectedFileForReading: string | null;
  isLoading: boolean;
  error: string | null;
  
  isLeftPanelCollapsed: boolean;
  leftPanelType: 'files' | 'history' | 'database';
  isRightPanelCollapsed: boolean;
  rightPanelWidth: number;
  isResizing: boolean;
  databaseManagerOpen: boolean;
  containerRef: React.RefObject<HTMLDivElement>;
  
  historyRefreshTrigger: number;
  processorResetTrigger: number;
  currentRecordId: string | null;
  
  projectId: string;
  
  setIsLeftPanelCollapsed: (collapsed: boolean) => void;
  setLeftPanelType: (type: 'files' | 'history' | 'database') => void;
  setIsRightPanelCollapsed: (collapsed: boolean) => void;
  setSelectedFiles: (files: FileItem[]) => void;
  setError: (error: string | null) => void;
  
  onFileSelect: (filepath: string) => void;
  onFileUpload: (files: File[]) => Promise<void>;
  onDeleteFile: (filepath: string) => Promise<void>;
  onRefreshFiles: () => Promise<void>;
  onSelectAll: () => void;
  onFileRead: (filepath: string) => void;
  
  onSelectRecord: (taskId: string) => Promise<void>;
  onNewSession: () => void;
  onTaskCompleted: (taskId: string) => void;
  onDeleteRecord: (taskId: string) => void;
  onHistoryFilesLoad: (files: FileItem[]) => void;
  
  onOpenDatabaseManager: () => void;
  onCloseDatabaseManager: () => void;
  handleMouseDown: (e: React.MouseEvent) => void;
  handleMouseMove: (e: MouseEvent) => void;
  handleMouseUp: () => void;
}

const Layout: React.FC<LayoutProps> = ({
  files,
  selectedFiles,
  selectedFileForReading,
  isLoading,
  error,
  isLeftPanelCollapsed,
  leftPanelType,
  isRightPanelCollapsed,
  rightPanelWidth,
  isResizing,
  databaseManagerOpen,
  containerRef,
  historyRefreshTrigger,
  processorResetTrigger,
  currentRecordId,
  projectId,
  setIsLeftPanelCollapsed,
  setLeftPanelType,
  setIsRightPanelCollapsed,
  setSelectedFiles,
  setError,
  onFileSelect,
  onFileUpload,
  onDeleteFile,
  onRefreshFiles,
  onSelectAll,
  onFileRead,
  onSelectRecord,
  onNewSession,
  onTaskCompleted,
  onDeleteRecord,
  onHistoryFilesLoad,
  onOpenDatabaseManager,
  onCloseDatabaseManager,
  handleMouseDown,
  handleMouseMove,
    handleMouseUp,
  }) => {
  useEffect(() => {
    if (isResizing) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    } else {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [isResizing, handleMouseMove, handleMouseUp]);

  return (
    <Box ref={containerRef} sx={{ height: '100vh', display: 'flex', overflow: 'hidden' }}>
      <LeftPanel
        isLeftPanelCollapsed={isLeftPanelCollapsed}
        leftPanelType={leftPanelType}
        files={files}
        selectedFiles={selectedFiles}
        selectedFilePaths={selectedFiles.map(f => f.filepath)}
        isLoading={isLoading}
        projectId={projectId}
        currentRecordId={currentRecordId}
        historyRefreshTrigger={historyRefreshTrigger}
        setLeftPanelType={setLeftPanelType}
        setIsLeftPanelCollapsed={setIsLeftPanelCollapsed}
        onFileSelect={onFileSelect}
        onFileUpload={onFileUpload}
        onDeleteFile={onDeleteFile}
        onRefreshFiles={onRefreshFiles}
        onSelectAll={onSelectAll}
        onFileRead={onFileRead}
        onNewSession={onNewSession}
        onSelectRecord={onSelectRecord}
        onDeleteRecord={onDeleteRecord}
        onOpenDatabaseManager={onOpenDatabaseManager}
      />

      <Box sx={{ 
        flexGrow: 1,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden'
      }}>
        <Container maxWidth="xl" sx={{ 
          height: '100%', 
          display: 'flex', 
          flexDirection: 'column', 
          py: 2, 
          px: 3,
          overflow: 'hidden'
        }}>
          {error && (
            <Alert 
              severity="error" 
              sx={{ mb: 2 }} 
              onClose={() => setError(null)}
            >
              {error}
            </Alert>
          )}

          <Box sx={{ 
            height: '100%', 
            display: 'flex', 
            flexDirection: 'column',
            gap: 2
          }}>
            <Paper sx={{ 
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              borderRadius: 2,
              overflow: 'hidden',
            }}>
              <Doc2DBProcessor
                key={processorResetTrigger}
                selectedFiles={selectedFiles}
                onClose={() => {}}
                onRemoveFile={(filepath) => {
                  setSelectedFiles(selectedFiles.filter(f => f.filepath !== filepath));
                }}
                projectId={projectId}
                onTaskCompleted={onTaskCompleted}
                onHistoryFilesLoad={onHistoryFilesLoad}
              />
            </Paper>
          </Box>
        </Container>
      </Box>

      <RightPanel
        isRightPanelCollapsed={isRightPanelCollapsed}
        rightPanelWidth={rightPanelWidth}
        isResizing={isResizing}
        selectedFileForReading={selectedFileForReading}
        projectId={projectId}
        setIsRightPanelCollapsed={setIsRightPanelCollapsed}
        handleMouseDown={handleMouseDown}
      />

      <Dialog 
        open={databaseManagerOpen} 
        onClose={onCloseDatabaseManager}
        maxWidth="xl"
        fullWidth
        PaperProps={{
          sx: { height: '90vh' }
        }}
      >
        <DialogTitle>
          Database Management
        </DialogTitle>
        <DialogContent sx={{ p: 0 }}>
          <DatabaseManager projectId={projectId} />
        </DialogContent>
        <DialogActions>
          <Button onClick={onCloseDatabaseManager}>Close</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default Layout;
