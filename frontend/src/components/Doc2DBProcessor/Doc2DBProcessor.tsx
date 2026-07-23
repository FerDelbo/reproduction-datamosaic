import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Alert,
  Fab,
  Tooltip
} from '@mui/material';
import {
  PlayArrow as PlayArrowIcon,
  Settings as SettingsIcon,
  Assessment as AssessmentIcon,
  TableChart as TableChartIcon,
  UnfoldMore as UnfoldMoreIcon,
  UnfoldLess as UnfoldLessIcon,
  KeyboardArrowUp as KeyboardArrowUpIcon
} from '@mui/icons-material';
import { Doc2DBProcessorProps } from './types';
import { useDoc2DBProcessor } from './hooks/useDoc2DBProcessor';
import ConfigSection from './components/ConfigSection';
import ProcessingSteps from './components/ProcessingSteps';
import SettingsDialog from './components/SettingsDialog';
import ResultsMemoryPage from './components/ResultsMemoryPage';

const Doc2DBProcessor: React.FC<Doc2DBProcessorProps> = ({
  selectedFiles,
  onClose,
  onRemoveFile,
  projectId,
  onTaskCompleted,
  onHistoryFilesLoad
}) => {
  const [currentPage, setCurrentPage] = useState<'settings' | 'analysis' | 'results'>('settings');
  
  const [hasExpandedSteps, setHasExpandedSteps] = useState(false);
  
  const {
    processing,
    taskId,
    status,
    error,
    configCollapsed,
    isHistoryMode,
    currentModel,
    settingsDialogOpen,
    apiKey,
    apiUrl,
    isSaving,
    saveMessage,
    memoryData,
    memoryLoading,
    inputMode,
    schemaMode,
    schemaInput,
    instructionInput,
    schemaForm,
    scrollContainerRef,
    processingMode,
    maxConcurrentTables,
    documentMode,
    
    setConfigCollapsed,
    setSettingsDialogOpen,
    setApiKey,
    setApiUrl,
    setInputMode,
    setSchemaMode,
    setSchemaInput,
    setInstructionInput,
    setSchemaForm,
    setTaskId,
    setStatus,
    setProcessing,
    setShouldKeepPolling,
    setProcessingMode,
    setMaxConcurrentTables,
    setDocumentMode,
    setIsHistoryMode,
    
    handleModelChange,
    handleSaveSettings,
    startProcessing,
    fetchMemoryData,
    validateFormSchema,
    validateJsonSchema,
    addColumn,
    removeColumn,
    updateColumn,
    convertFormToJson,
    convertJsonToForm,
    addTable,
    removeTable,
    updateTableName,
    updateTableType,
    addRelation,
    removeRelation,
    updateRelation,
    currentTableIndex,
    setCurrentTableIndex,
  } = useDoc2DBProcessor(selectedFiles, onTaskCompleted, onHistoryFilesLoad);

  const removeSelectedFile = (filepath: string) => {
    if (onRemoveFile) {
      onRemoveFile(filepath);
    }
  };

  const handleReset = () => {
    setTaskId(null);
    setStatus(null);
    setProcessing(false);
    setShouldKeepPolling(false);
    setIsHistoryMode(false); // Exit history mode
  };

  const [shouldAutoSwitchToAnalysis, setShouldAutoSwitchToAnalysis] = useState(false);

  const handleReAnalyze = () => {
    setTaskId(null);
    setStatus(null);
    setProcessing(false);
    setShouldKeepPolling(false);
    setIsHistoryMode(false); // Exit history mode
    
    setShouldAutoSwitchToAnalysis(true);
    
    setTimeout(() => {
      startProcessing();
    }, 0);
  };

  const canEnterAnalysis = taskId !== null || processing || isHistoryMode;
  
  const canEnterResults = status?.status === 'completed';

  const handleStartProcessing = () => {
    setShouldAutoSwitchToAnalysis(true);
    startProcessing();
  };

  useEffect(() => {
    if (processing && shouldAutoSwitchToAnalysis && currentPage !== 'analysis') {
      setCurrentPage('analysis');
      setShouldAutoSwitchToAnalysis(false);
    }
  }, [processing, shouldAutoSwitchToAnalysis, currentPage]);

  useEffect(() => {
    if (isHistoryMode && taskId) {
      setCurrentPage('settings');
      setShouldAutoSwitchToAnalysis(false);
    }
  }, [isHistoryMode, taskId]);

  const handleToggleAllSteps = () => {
    if ((window as any).toggleProcessingSteps) {
      (window as any).toggleProcessingSteps();
      setHasExpandedSteps(!hasExpandedSteps);
    }
  };

  useEffect(() => {
    const checkExpandedState = () => {
      if ((window as any).getProcessingStepsExpandedState) {
        const actualState = (window as any).getProcessingStepsExpandedState();
        if (actualState !== hasExpandedSteps) {
          setHasExpandedSteps(actualState);
        }
      }
    };

    const interval = setInterval(checkExpandedState, 500);
    return () => clearInterval(interval);
  }, [hasExpandedSteps]);

  const handleScrollToTop = () => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTo({
        top: 0,
        behavior: 'smooth'
      });
    }
  };

  return (
    <Box sx={{ 
      width: '100%', 
      height: '100vh', 
      display: 'flex', 
      flexDirection: 'column',
      bgcolor: '#white',
      p: 4,
      gap: 4,
      overflow: 'hidden'
    }}>
      <Box sx={{ 
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        pb: 3,
        pt: 1
      }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0, position: 'relative' }}>
          <Box
            onClick={() => setCurrentPage('settings')}
            sx={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              cursor: 'pointer',
              position: 'relative',
              zIndex: 2
            }}
          >
            <Box sx={{
              width: 40,
              height: 40,
              borderRadius: '50%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              bgcolor: currentPage === 'settings' || canEnterAnalysis ? '#0d6efd' : '#e9ecef',
              color: 'white',
              mb: 1.5,
              transition: 'all 0.3s ease',
              border: currentPage === 'settings' ? '3px solid #0d6efd' : '3px solid transparent',
              boxShadow: currentPage === 'settings' 
                ? '0 0 0 4px rgba(13, 110, 253, 0.2)' 
                : 'none',
              '&:hover': {
                transform: 'scale(1.05)'
              }
            }}>
              <SettingsIcon sx={{ fontSize: 20 }} />
            </Box>
            <Typography sx={{
              fontSize: '0.875rem',
              fontWeight: currentPage === 'settings' ? 600 : 500,
              color: currentPage === 'settings' ? '#0d6efd' : '#6c757d',
              transition: 'all 0.3s ease'
            }}>
              Task Settings
            </Typography>
          </Box>
          <Box sx={{
            width: 80,
            height: 3,
            bgcolor: canEnterAnalysis ? '#0d6efd' : '#e9ecef',
            mb: 6,
            mx: -1,
            transition: 'all 0.3s ease',
            position: 'relative',
            zIndex: 1
          }} />
          <Box
            onClick={() => canEnterAnalysis && setCurrentPage('analysis')}
            sx={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              cursor: canEnterAnalysis ? 'pointer' : 'default',
              position: 'relative',
              zIndex: 2,
              opacity: canEnterAnalysis ? 1 : 0.5
            }}
          >
            <Box sx={{
              width: 40,
              height: 40,
              borderRadius: '50%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              bgcolor: canEnterAnalysis ? '#0d6efd' : '#e9ecef',
              color: canEnterAnalysis ? 'white' : '#adb5bd',
              mb: 1.5,
              transition: 'all 0.3s ease',
              border: currentPage === 'analysis' ? '3px solid #0d6efd' : '3px solid transparent',
              boxShadow: currentPage === 'analysis' 
                ? '0 0 0 4px rgba(13, 110, 253, 0.2)' 
                : 'none',
              '&:hover': canEnterAnalysis ? {
                transform: 'scale(1.05)'
              } : {}
            }}>
              <AssessmentIcon sx={{ fontSize: 20 }} />
            </Box>
            <Typography sx={{
              fontSize: '0.875rem',
              fontWeight: currentPage === 'analysis' ? 600 : 500,
              color: currentPage === 'analysis' ? '#0d6efd' : '#6c757d',
              transition: 'all 0.3s ease'
            }}>
              Analysis Details
            </Typography>
          </Box>
          <Box sx={{
            width: 80,
            height: 3,
            bgcolor: canEnterResults ? '#0d6efd' : '#e9ecef',
            mb: 6,
            mx: -1,
            transition: 'all 0.3s ease',
            position: 'relative',
            zIndex: 1
          }} />
          <Box
            onClick={() => canEnterResults && setCurrentPage('results')}
            sx={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              cursor: canEnterResults ? 'pointer' : 'default',
              position: 'relative',
              zIndex: 2,
              opacity: canEnterResults ? 1 : 0.5
            }}
          >
            <Box sx={{
              width: 40,
              height: 40,
              borderRadius: '50%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              bgcolor: canEnterResults ? '#0d6efd' : '#e9ecef',
              color: canEnterResults ? 'white' : '#adb5bd',
              mb: 1.5,
              transition: 'all 0.3s ease',
              border: currentPage === 'results' ? '3px solid #0d6efd' : '3px solid transparent',
              boxShadow: currentPage === 'results' 
                ? '0 0 0 4px rgba(13, 110, 253, 0.2)' 
                : 'none',
              '&:hover': canEnterResults ? {
                transform: 'scale(1.05)'
              } : {}
            }}>
              <TableChartIcon sx={{ fontSize: 20 }} />
            </Box>
            <Typography sx={{
              fontSize: '0.875rem',
              fontWeight: currentPage === 'results' ? 600 : 500,
              color: currentPage === 'results' ? '#0d6efd' : '#6c757d',
              transition: 'all 0.3s ease'
            }}>
              Results & Memory
            </Typography>
          </Box>
        </Box>
      </Box>
      {error && (
        <Alert 
          severity="error" 
          sx={{ 
            borderRadius: 3,
            border: '1px solid #f5c2c7',
            bgcolor: '#f8d7da',
            '& .MuiAlert-message': {
              fontSize: '0.875rem',
              color: '#842029'
            },
            '& .MuiAlert-icon': {
              color: '#dc3545'
            }
          }}
        >
          {error}
        </Alert>
      )}
      <Box sx={{ 
        flex: 1,
        position: 'relative',
        overflow: 'hidden',
        minHeight: 0,
        borderRadius: 4,
        bgcolor: 'white',
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.12)',
        border: '1px solid rgba(255, 255, 255, 0.8)'
      }}>
        <Box
          sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            transform: currentPage === 'settings' ? 'translateX(0)' : 'translateX(-100%)',
            transition: 'all 0.6s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
            opacity: currentPage === 'settings' ? 1 : 0.8,
            visibility: currentPage === 'settings' ? 'visible' : 'hidden',
            overflow: 'auto',
            zIndex: currentPage === 'settings' ? 2 : 1,
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
          }}
        >
          <ConfigSection
            configCollapsed={false}
            selectedFiles={selectedFiles}
            processing={processing}
            currentModel={currentModel}
            inputMode={inputMode}
            schemaMode={schemaMode}
            instructionInput={instructionInput}
            schemaInput={schemaInput}
            schemaForm={schemaForm}
            processingMode={processingMode}
            maxConcurrentTables={maxConcurrentTables}
            documentMode={documentMode}
            currentTableIndex={currentTableIndex}
            hasCompletedTask={status?.status === 'completed'}
            validateJsonSchema={validateJsonSchema}
            validateFormSchema={validateFormSchema}
            setConfigCollapsed={setConfigCollapsed}
            setInputMode={setInputMode}
            setSchemaMode={setSchemaMode}
            setInstructionInput={setInstructionInput}
            setSchemaInput={setSchemaInput}
            setSchemaForm={setSchemaForm}
            setProcessingMode={setProcessingMode}
            setMaxConcurrentTables={setMaxConcurrentTables}
            setDocumentMode={setDocumentMode}
            setCurrentTableIndex={setCurrentTableIndex}
            handleModelChange={handleModelChange}
            startProcessing={handleStartProcessing}
            removeSelectedFile={removeSelectedFile}
            addColumn={addColumn}
            removeColumn={removeColumn}
            updateColumn={updateColumn}
            convertFormToJson={convertFormToJson}
            convertJsonToForm={convertJsonToForm}
            addTable={addTable}
            removeTable={removeTable}
            updateTableName={updateTableName}
            updateTableType={updateTableType}
            addRelation={addRelation}
            removeRelation={removeRelation}
            updateRelation={updateRelation}
            onResetTask={handleReAnalyze}
          />
        </Box>
        <Box
          sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            transform: currentPage === 'analysis' ? 'translateX(0)' : 
                       currentPage === 'settings' ? 'translateX(100%)' : 'translateX(-100%)',
            transition: 'all 0.6s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
            opacity: currentPage === 'analysis' ? 1 : 0.8,
            visibility: currentPage === 'analysis' ? 'visible' : 'hidden',
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            zIndex: currentPage === 'analysis' ? 2 : 1
          }}
        >
          <Box sx={{ 
            flex: 1,
            display: 'flex',
            minHeight: 0,
            overflow: 'hidden',
            p: 4
          }}>
            <Box 
              ref={scrollContainerRef}
              sx={{ 
                flex: 1, 
                overflow: 'auto',
                scrollBehavior: 'smooth',
                minHeight: 0,
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
              }}
            >
              {!taskId && !processing && !isHistoryMode ? (
                <Box sx={{ 
                  display: 'flex', 
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  height: '100%',
                  textAlign: 'center',
                  py: 8
                }}>
                  <Box sx={{
                    width: 80,
                    height: 80,
                    borderRadius: 4,
                    background: 'linear-gradient(135deg, #0d6efd 0%, #6610f2 100%)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    mb: 4,
                    boxShadow: '0 8px 32px rgba(13, 110, 253, 0.3)'
                  }}>
                    <PlayArrowIcon sx={{ fontSize: 36, color: 'white' }} />
                  </Box>
                  <Typography variant="h6" sx={{ mb: 2, fontWeight: 600, color: '#111827', fontSize: '0.95rem' }}>
                    Wait for Analysis
                  </Typography>
                  <Typography variant="body2" sx={{ color: '#6c757d', maxWidth: 400, lineHeight: 1.6, fontSize: '0.8rem' }}>
                    After configuring the processing method and files, click the "Begin Analysis" button, and the system will display the process in real time
                  </Typography>
                </Box>
              ) : (
                <Box sx={{ 
                  width: '100%',
                  minHeight: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  flex: 1
                }}>
                  <ProcessingSteps 
                    status={status} 
                    projectId={projectId}
                    onToggleAllSteps={handleToggleAllSteps}
                    onScrollToTop={handleScrollToTop}
                    hasExpandedSteps={hasExpandedSteps}
                    processing={processing}
                  />
                </Box>
              )}
            </Box>
          </Box>
          {currentPage === 'analysis' && (taskId || processing || isHistoryMode) && (
            <Box sx={{
              position: 'absolute',
              bottom: 60,
              right: 32,
              display: 'flex',
              flexDirection: 'column',
              gap: 2,
              zIndex: 1000
            }}>
              <Tooltip title="">
                <Fab
                  size="medium"
                  color="primary"
                  onClick={handleScrollToTop}
                  sx={{
                    bgcolor: '#0d6efd',
                    '&:hover': {
                      bgcolor: '#0b5ed7'
                    },
                    boxShadow: '0 4px 20px rgba(13, 110, 253, 0.3)'
                  }}
                >
                  <KeyboardArrowUpIcon />
                </Fab>
              </Tooltip>
              <Tooltip title={hasExpandedSteps ? "Collapse All" : "Expand All"} placement="right">
                <Fab
                  size="medium"
                  color="secondary"
                  onClick={handleToggleAllSteps}
                  sx={{
                    bgcolor: '#6c757d',
                    color: 'white',
                    '&:hover': {
                      bgcolor: '#5a6268'
                    },
                    boxShadow: '0 4px 20px rgba(108, 117, 125, 0.3)'
                  }}
                >
                  {hasExpandedSteps ? <UnfoldLessIcon /> : <UnfoldMoreIcon />}
                </Fab>
              </Tooltip>
            </Box>
          )}
        </Box>
        <Box
          sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            transform: currentPage === 'results' ? 'translateX(0)' : 'translateX(100%)',
            transition: 'all 0.6s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
            opacity: currentPage === 'results' ? 1 : 0.8,
            visibility: currentPage === 'results' ? 'visible' : 'hidden',
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            zIndex: currentPage === 'results' ? 2 : 1
          }}
        >
          {canEnterResults ? (
            <ResultsMemoryPage
              status={status}
              projectId={projectId}
              memoryData={memoryData}
              memoryLoading={memoryLoading}
              taskId={taskId}
              runId={status?.result_context?.run_id}
              fetchMemoryData={fetchMemoryData}
            />
          ) : (
            <Box sx={{ 
              display: 'flex', 
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              textAlign: 'center',
              p: 8
            }}>
              <Box sx={{
                width: 80,
                height: 80,
                borderRadius: 4,
                background: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                mb: 4,
                boxShadow: '0 8px 32px rgba(245, 158, 11, 0.3)'
              }}>
                <TableChartIcon sx={{ fontSize: 36, color: 'white' }} />
              </Box>
              <Typography variant="h6" sx={{ mb: 2, fontWeight: 600, color: '#111827', fontSize: '0.95rem' }}>
                Waiting for task completion
              </Typography>
              <Typography variant="body2" sx={{ color: '#6c757d', maxWidth: 400, lineHeight: 1.6, fontSize: '0.8rem' }}>
                After the task is completed, you can view extraction results and memory data here
              </Typography>
            </Box>
          )}
        </Box>
      </Box>
      <SettingsDialog
        open={settingsDialogOpen}
        onClose={() => setSettingsDialogOpen(false)}
        currentModel={currentModel}
        apiKey={apiKey}
        apiUrl={apiUrl}
        isSaving={isSaving}
        saveMessage={saveMessage}
        setCurrentModel={(model) => {}} // Model changes are already handled in handleModelChange
        setApiKey={setApiKey}
        setApiUrl={setApiUrl}
        onSave={handleSaveSettings}
      />
    </Box>
  );
};

export default Doc2DBProcessor;
