/**
 * Hook that manages Doc2DB processing state
 */
import { useState, useCallback } from 'react';
import { PROJECT_ID } from '../constants/config';

export const useDoc2DB = () => {
  const [historyRefreshTrigger, setHistoryRefreshTrigger] = useState<number>(0);
  const [processorResetTrigger, setProcessorResetTrigger] = useState<number>(0);
  const [currentRecordId, setCurrentRecordId] = useState<string | null>(null);

  const handleSelectRecord = useCallback(async (taskId: string, setError: (error: string | null) => void) => {
    try {
      setError(null);
      setCurrentRecordId(taskId);

      const response = await fetch(`/api/projects/${PROJECT_ID}/doc2db/history/${taskId}/details`);

      if (response.ok) {
        const taskDetails = await response.json();
        (window as any).selectedHistoryTaskId = taskId;
        (window as any).selectedHistoryTaskDetails = taskDetails;
      } else {
        const errorData = await response.json();
        setError(errorData.error || 'Failed to fetch task details');
      }
    } catch (err) {
      console.error('Failed to fetch task details:', err);
      setError('Network connection failed');
    }
  }, []);

  const handleNewSession = useCallback(() => {
    setCurrentRecordId(null);
    delete (window as any).selectedHistoryTaskId;
    delete (window as any).selectedHistoryTaskDetails;
    setHistoryRefreshTrigger(prev => prev + 1);
    setProcessorResetTrigger(prev => prev + 1);
  }, []);

  const handleTaskCompleted = useCallback((completedTaskId: string) => {
    setCurrentRecordId(completedTaskId);
    setHistoryRefreshTrigger(prev => prev + 1);
  }, []);

  const handleDeleteRecord = useCallback((deletedTaskId: string) => {
    if (currentRecordId === deletedTaskId) {
      setCurrentRecordId(null);
      delete (window as any).selectedHistoryTaskId;
      delete (window as any).selectedHistoryTaskDetails;
      setProcessorResetTrigger(prev => prev + 1);
    }
    setHistoryRefreshTrigger(prev => prev + 1);
  }, [currentRecordId]);

  return {
    historyRefreshTrigger,
    processorResetTrigger,
    currentRecordId,
    setHistoryRefreshTrigger,
    setProcessorResetTrigger,
    setCurrentRecordId,
    handleSelectRecord,
    handleNewSession,
    handleTaskCompleted,
    handleDeleteRecord,
  };
};
