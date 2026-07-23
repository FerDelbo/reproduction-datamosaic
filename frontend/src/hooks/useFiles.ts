/**
 * Custom hook for file management
 */
import { useState, useCallback } from 'react';
import { FileItem, PROJECT_ID } from '../constants/config';

export const useFiles = () => {
  const [files, setFiles] = useState<FileItem[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<FileItem[]>([]);
  const [selectedFileForReading, setSelectedFileForReading] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchUploadedFiles = useCallback(async (skipLoading = false) => {
    if (!skipLoading) {
      setIsLoading(true);
    }
    setError(null);
    try {
      const response = await fetch(`/api/projects/${PROJECT_ID}/files`);
      if (response.ok) {
        const data = await response.json();
        setFiles(data.files || []);
      } else {
        const errorData = await response.json();
        setError(errorData.error || 'Failed to load file list');
      }
    } catch (err) {
      setError('Network connection failed');
      console.error('Error fetching files:', err);
    } finally {
      if (!skipLoading) {
        setIsLoading(false);
      }
    }
  }, []);

  const handleFileUpload = useCallback(async (uploadedFiles: File[]) => {
    setIsLoading(true);
    setError(null);

    try {
      const formData = new FormData();
      uploadedFiles.forEach(file => {
        formData.append('files', file);
      });

      const response = await fetch(`/api/projects/${PROJECT_ID}/upload/batch`, {
        method: 'POST',
        body: formData,
      });

      const result = await response.json();

      if (response.ok) {
        await fetchUploadedFiles(true);
        const { summary } = result;
        if (summary?.uploaded_count > 0) {
        }
        if (summary?.failed_count > 0) {
          console.warn(`${summary.failed_count} file(s) failed to upload`);
        }
      } else {
        setError(result.error || 'File upload failed');
      }
    } catch (err) {
      setError('An error occurred during upload');
      console.error('Upload error:', err);
    } finally {
      setIsLoading(false);
    }
  }, [fetchUploadedFiles]);

  const handleFileDelete = useCallback(async (filepath: string) => {
    setIsLoading(true);
    try {
      const response = await fetch(`/api/projects/${PROJECT_ID}/files/delete`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ filepath }),
      });

      if (response.ok) {
        await fetchUploadedFiles(true);
        if (selectedFileForReading === filepath) {
          setSelectedFileForReading(null);
        }
        setSelectedFiles(prev => prev.filter(f => f.filepath !== filepath));
      } else {
        const errorData = await response.json();
        setError(errorData.error || 'Failed to delete file');
      }
    } catch (err) {
      setError('An error occurred while deleting file');
      console.error('Delete error:', err);
    } finally {
      setIsLoading(false);
    }
  }, [selectedFileForReading, fetchUploadedFiles]);

  const toggleFileSelection = useCallback((filepath: string) => {
    const fileIndex = files.findIndex(file => file.filepath === filepath);
    if (fileIndex === -1) return;

    const file = files[fileIndex];
    const isCurrentlySelected = selectedFiles.some(f => f.filepath === filepath);

    if (isCurrentlySelected) {
      setSelectedFiles(selectedFiles.filter(f => f.filepath !== filepath));
    } else {
      setSelectedFiles([...selectedFiles, file]);
    }
  }, [files, selectedFiles]);

  const handleSelectAll = useCallback(() => {
    if (selectedFiles.length === files.length) {
      setSelectedFiles([]);
    } else {
      setSelectedFiles([...files]);
    }
  }, [selectedFiles, files]);

  const handleFileRead = useCallback((filepath: string) => {
    setSelectedFileForReading(filepath);
  }, []);

  return {
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
  };
};
