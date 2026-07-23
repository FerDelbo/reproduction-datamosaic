/**
 * Doc2DB application root component
 */
import React, { useEffect } from 'react';
import { ThemeProvider, CssBaseline } from '@mui/material';

import Layout from './components/Layout';
import { theme } from './constants/theme';
import { PROJECT_ID } from './constants/config';
import { useFiles } from './hooks/useFiles';
import { usePanel } from './hooks/usePanel';
import { useDoc2DB } from './hooks/useDoc2DB';

function App() {
  const {
    files,
    selectedFiles,
    selectedFileForReading,
    isLoading,
    error,
    setSelectedFiles,
    setSelectedFileForReading,
    setError,
    fetchUploadedFiles,
    handleFileUpload,
    handleFileDelete,
    toggleFileSelection,
    handleSelectAll,
    handleFileRead,
  } = useFiles();

  const {
    isLeftPanelCollapsed,
    leftPanelType,
    isRightPanelCollapsed,
    rightPanelWidth,
    isResizing,
    setIsLeftPanelCollapsed,
    setLeftPanelType,
    setIsRightPanelCollapsed,
    databaseManagerOpen,
    handleOpenDatabaseManager,
    handleCloseDatabaseManager,
    containerRef,
    handleMouseDown,
    handleMouseMove,
    handleMouseUp,
  } = usePanel();

  const {
    historyRefreshTrigger,
    processorResetTrigger,
    currentRecordId,
    handleSelectRecord,
    handleNewSession,
    handleTaskCompleted,
    handleDeleteRecord,
  } = useDoc2DB();

  useEffect(() => {
    fetchUploadedFiles();
  }, [fetchUploadedFiles]);

  const handleNewSessionWithCleanup = () => {
    setSelectedFiles([]);
    setSelectedFileForReading(null);
    setError(null);
    setIsRightPanelCollapsed(true);
    handleNewSession();
  };

  const handleFileReadWithPanel = (filepath: string) => {
    handleFileRead(filepath);
    setIsRightPanelCollapsed(false);
  };

  const handleSelectRecordWithError = (taskId: string) => {
    return handleSelectRecord(taskId, setError);
  };

  const handleHistoryFilesLoad = (files: any[]) => {
    setSelectedFiles(files);
  };

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Layout
        files={files}
        selectedFiles={selectedFiles}
        selectedFileForReading={selectedFileForReading}
        isLoading={isLoading}
        error={error}
        
        isLeftPanelCollapsed={isLeftPanelCollapsed}
        leftPanelType={leftPanelType}
        isRightPanelCollapsed={isRightPanelCollapsed}
        rightPanelWidth={rightPanelWidth}
        isResizing={isResizing}
        databaseManagerOpen={databaseManagerOpen}
        containerRef={containerRef}
        
        historyRefreshTrigger={historyRefreshTrigger}
        processorResetTrigger={processorResetTrigger}
        currentRecordId={currentRecordId}
        
        projectId={PROJECT_ID}
        
        setIsLeftPanelCollapsed={setIsLeftPanelCollapsed}
        setLeftPanelType={setLeftPanelType}
        setIsRightPanelCollapsed={setIsRightPanelCollapsed}
        setSelectedFiles={setSelectedFiles}
        setError={setError}
        
        onFileSelect={toggleFileSelection}
        onFileUpload={handleFileUpload}
        onDeleteFile={handleFileDelete}
        onRefreshFiles={fetchUploadedFiles}
        onSelectAll={handleSelectAll}
        onFileRead={handleFileReadWithPanel}
        
        onSelectRecord={handleSelectRecordWithError}
        onNewSession={handleNewSessionWithCleanup}
        onTaskCompleted={handleTaskCompleted}
        onDeleteRecord={handleDeleteRecord}
        onHistoryFilesLoad={handleHistoryFilesLoad}
        
        onOpenDatabaseManager={handleOpenDatabaseManager}
        onCloseDatabaseManager={handleCloseDatabaseManager}
        handleMouseDown={handleMouseDown}
        handleMouseMove={handleMouseMove}
        handleMouseUp={handleMouseUp}
      />
    </ThemeProvider>
  );
}

export default App;
