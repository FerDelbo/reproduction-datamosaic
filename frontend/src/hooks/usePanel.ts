/**
 * Custom hook that manages panel state
 */
import { useState, useCallback, useRef } from 'react';

export const usePanel = () => {
  const [isLeftPanelCollapsed, setIsLeftPanelCollapsed] = useState(false);
  const [leftPanelType, setLeftPanelType] = useState<'files' | 'history' | 'database'>('files');
  const [isRightPanelCollapsed, setIsRightPanelCollapsed] = useState(true);
  const [rightPanelWidth, setRightPanelWidth] = useState(500);
  const [isResizing, setIsResizing] = useState(false);
  const [databaseManagerOpen, setDatabaseManagerOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
  }, []);

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isResizing || !containerRef.current) return;

    const containerRect = containerRef.current.getBoundingClientRect();
    const containerWidth = containerRect.width;
    const mouseX = e.clientX - containerRect.left;
    const newWidth = containerWidth - mouseX;
    const minWidth = 300;
    const maxWidth = Math.floor(containerWidth * 0.5);
    const clampedWidth = Math.max(minWidth, Math.min(maxWidth, newWidth));

    setRightPanelWidth(clampedWidth);
  }, [isResizing]);

  const handleMouseUp = useCallback(() => {
    setIsResizing(false);
  }, []);

  const handleOpenDatabaseManager = useCallback(() => {
    setDatabaseManagerOpen(true);
  }, []);

  const handleCloseDatabaseManager = useCallback(() => {
    setDatabaseManagerOpen(false);
  }, []);

  return {
    isLeftPanelCollapsed,
    leftPanelType,
    setIsLeftPanelCollapsed,
    setLeftPanelType,
    isRightPanelCollapsed,
    rightPanelWidth,
    isResizing,
    setIsRightPanelCollapsed,
    setRightPanelWidth,
    setIsResizing,
    databaseManagerOpen,
    handleOpenDatabaseManager,
    handleCloseDatabaseManager,
    containerRef,
    handleMouseDown,
    handleMouseMove,
    handleMouseUp,
  };
};
