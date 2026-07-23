import React, { useState } from 'react';
import {
  Box,
  Typography,
  CircularProgress,
  Stack,
  Alert,
  IconButton,
  Button
} from '@mui/material';
import {
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
  Schedule as ScheduleIcon,
  Settings as SettingsIcon,
  Description as DescriptionIcon,
  TableChart as TableChartIcon,
  Edit as EditIcon,
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
  UnfoldMore as UnfoldMoreIcon,
  UnfoldLess as UnfoldLessIcon
} from '@mui/icons-material';
import { ProcessingStatus, ProcessingStep } from '../types';
import { getStepDisplayName } from '../utils/processingUtils';
import SmartContentCard from './SmartContentCard';

interface ProcessingStepsProps {
  status: ProcessingStatus | null;
  projectId?: string;
  onToggleAllSteps?: () => void;
  onScrollToTop?: () => void;
  hasExpandedSteps?: boolean;
  processing?: boolean;
}

const ProcessingSteps: React.FC<ProcessingStepsProps> = ({ 
  status, 
  projectId, 
  onToggleAllSteps, 
  onScrollToTop, 
  hasExpandedSteps: externalHasExpandedSteps,
  processing = false
}) => {
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(() => {
    if (!status || !status.steps?.length) return new Set();
    
    const collapsedSteps = [
      'orchestrator_start',
      'extractor_completed',
      'extractor_document',
      'multi_table_verification_completed',
      'verifier_completed',
      'orchestrator_completion',
      'multi_table_verification_detailed',
      'multi_table_verification_completed',
    ];
    
    const initialExpanded = new Set<string>();
    
    status.steps.forEach((step, index) => {
      const stepName = step.step_name || step.step || '';
      const stepTimestamp = step.timestamp || step.start_time || '';
      const uniqueStepId = `${stepName}_${stepTimestamp}_${index}`;
      const shouldDefaultCollapse = collapsedSteps.some(collapsed => stepName.includes(collapsed));
      
      if (!shouldDefaultCollapse) {
        initialExpanded.add(uniqueStepId);
      }
    });
    
    return initialExpanded;
  });

  const collapsedSteps = [
    'orchestrator_start',
    'extractor_completed',
    'extractor_document',
    'multi_table_verification_completed',
    'verifier_completed',
    'orchestrator_completion',
    'multi_table_verification_detailed',
    'multi_table_verification_completed',
  ];

  const shouldDefaultCollapse = (stepName: string) => {
    return collapsedSteps.some(collapsed => stepName.includes(collapsed));
  };

  const toggleStepExpansion = (stepName: string) => {
    setExpandedSteps(prev => {
      const newSet = new Set(prev);
      if (newSet.has(stepName)) {
        newSet.delete(stepName);
      } else {
        newSet.add(stepName);
      }
      return newSet;
    });
  };

  const filteredSteps = status?.status === 'completed' || status?.status === 'failed' 
    ? status.steps?.filter(step => step.status !== 'running') || []
    : status?.steps || [];

  const expandAllSteps = () => {
    if (!status || !status.steps?.length) return;
    
    const allStepIds = new Set<string>();
    filteredSteps.forEach((step, index) => {
      const stepName = step.step_name || step.step || '';
      const stepTimestamp = step.timestamp || step.start_time || '';
      const uniqueStepId = `${stepName}_${stepTimestamp}_${index}`;
      allStepIds.add(uniqueStepId);
    });
    setExpandedSteps(allStepIds);
  };

  const collapseAllSteps = () => {
    setExpandedSteps(new Set());
  };

  const hasExpandedSteps = externalHasExpandedSteps ?? expandedSteps.size > 0;

  React.useEffect(() => {
    (window as any).toggleProcessingSteps = () => {
      if (hasExpandedSteps) {
        collapseAllSteps();
      } else {
        expandAllSteps();
      }
    };

    (window as any).getProcessingStepsExpandedState = () => {
      return expandedSteps.size > 0;
    };
  }, [hasExpandedSteps, expandedSteps.size]);

  React.useEffect(() => {
    if (onToggleAllSteps) {
    }
  }, [expandedSteps.size, onToggleAllSteps]);

  const hasRunningSteps = status?.steps?.some(step => step.status === 'running') || false;
  

  if (!status || !status.steps?.length) {
    return null;
  }


  const isStepExpanded = (stepName: string) => {
    return expandedSteps.has(stepName);
  };

  const getStepIcon = (step: ProcessingStep, isCollapsed: boolean = false) => {
    if (step.step_name?.includes('orchestrator')) {
      if (isCollapsed) return <SettingsIcon sx={{ color: '#374151', fontSize: 24 }} />;
      if (step.status === 'completed') return <SettingsIcon sx={{ color: '#059669', fontSize: 24 }} />;
      if (step.status === 'failed') return <ErrorIcon color="error" />;
      if (step.status === 'running') return <CircularProgress size={20} sx={{ color: '#1976d2' }} />;
      return <SettingsIcon sx={{ color: '#9ca3af', fontSize: 24 }} />;
    }
    
    if (step.step_name?.includes('extractor')) {
      if (isCollapsed) return <DescriptionIcon sx={{ color: '#374151', fontSize: 24 }} />;
      if (step.status === 'completed') return <DescriptionIcon sx={{ color: '#059669', fontSize: 24 }} />;
      if (step.status === 'failed') return <ErrorIcon color="error" />;
      if (step.status === 'running') return <CircularProgress size={20} sx={{ color: '#1976d2' }} />;
      return <DescriptionIcon sx={{ color: '#9ca3af', fontSize: 24 }} />;
    }
    
    if (step.step_name?.includes('verifier')) {
      if (isCollapsed) return <CheckCircleIcon sx={{ color: '#374151', fontSize: 24 }} />;
      if (step.status === 'completed') return <CheckCircleIcon sx={{ color: '#059669', fontSize: 24 }} />;
      if (step.status === 'failed') return <ErrorIcon color="error" />;
      if (step.status === 'running') return <CircularProgress size={20} sx={{ color: '#1976d2' }} />;
      return <CheckCircleIcon sx={{ color: '#9ca3af', fontSize: 24 }} />;
    }
    
    if (step.step_name?.includes('fixer')) {
      if (isCollapsed) return <EditIcon sx={{ color: '#374151', fontSize: 24 }} />;
      if (step.status === 'completed') return <EditIcon sx={{ color: '#059669', fontSize: 24 }} />;
      if (step.status === 'failed') return <ErrorIcon color="error" />;
      if (step.status === 'running') return <CircularProgress size={20} sx={{ color: '#1976d2' }} />;
      return <EditIcon sx={{ color: '#9ca3af', fontSize: 24 }} />;
    }
    
    if (isCollapsed) return <CheckCircleIcon sx={{ color: '#374151' }} />;
    
    switch (step.status) {
      case 'completed':
        return <CheckCircleIcon color="success" />;
      case 'failed':
        return <ErrorIcon color="error" />;
      case 'running':
        return <CircularProgress size={24} />;
      default:
        return <ScheduleIcon color="disabled" />;
    }
  };

  const renderStepDetails = (details: any, step?: any) => {
    if (!details && !step) return null;
    
    const detailsToRender = step || details;
    const actualDetails = details || (step?.details);
    
    if ((step?.step_name || step?.step)?.includes('verifier') && actualDetails && actualDetails.mcp_results) {
      const mcpResults = actualDetails.mcp_results;
      return (
        <Box>
          <Box sx={{ 
            display: 'flex', 
            gap: 1.5, 
            mb: 2, 
            flexWrap: 'wrap',
            p: 1.5,
            bgcolor: '#f0f9ff',
            borderRadius: 1.5,
            border: '1px solid #bae6fd'
          }}>
            <Box sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 0.5,
              px: 1.5,
              py: 0.5,
              bgcolor: '#dbeafe',
              borderRadius: 1,
              fontSize: '0.75rem',
              color: '#1e40af'
            }}>
              <CheckCircleIcon sx={{ fontSize: 14 }} />
              Total Violations: {actualDetails.violations_found || 0}
            </Box>
            {actualDetails.error_violations > 0 && (
              <Box sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 0.5,
                px: 1.5,
                py: 0.5,
                bgcolor: '#fee2e2',
                borderRadius: 1,
                fontSize: '0.75rem',
                color: '#dc2626'
              }}>
                Errors: {actualDetails.error_violations}
              </Box>
            )}
            {actualDetails.warn_violations > 0 && (
              <Box sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 0.5,
                px: 1.5,
                py: 0.5,
                bgcolor: '#fef3c7',
                borderRadius: 1,
                fontSize: '0.75rem',
                color: '#92400e'
              }}>
                Warnings: {actualDetails.warn_violations}
              </Box>
            )}
          </Box>
          <Box sx={{ mb: 2 }}>
            <Typography variant="subtitle2" sx={{ mb: 1.5, fontWeight: 600, color: '#374151', fontSize: '0.875rem' }}>
              MCP Check Results:
            </Typography>
            <Stack spacing={1}>
              {mcpResults.map((mcp: any, index: number) => (
                <Box key={index} sx={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  p: 1.5,
                  bgcolor: mcp.status === 'passed' ? '#f0fdf4' : '#fef2f2',
                  borderRadius: 1,
                  border: `1px solid ${mcp.status === 'passed' ? '#bbf7d0' : '#fecaca'}`
                }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    {mcp.status === 'passed' ? (
                      <CheckCircleIcon sx={{ fontSize: 18, color: '#16a34a' }} />
                    ) : (
                      <ErrorIcon sx={{ fontSize: 18, color: '#dc2626' }} />
                    )}
                    <Typography sx={{ fontSize: '0.8rem', fontWeight: 500, color: '#374151' }}>
                      {mcp.mcp_name}
                    </Typography>
                  </Box>
                  <Box sx={{
                    px: 1.5,
                    py: 0.5,
                    bgcolor: mcp.status === 'passed' ? '#dcfce7' : '#fee2e2',
                    borderRadius: 1,
                    fontSize: '0.75rem',
                    color: mcp.status === 'passed' ? '#166534' : '#dc2626',
                    fontWeight: 500
                  }}>
                    {mcp.violations_found > 0 ? `Found ${mcp.violations_found} issues` : '✓ Passed'}
                  </Box>
                </Box>
              ))}
            </Stack>
          </Box>
          {actualDetails.output_text && (
            <SmartContentCard
              title="Verification Details"
              content={actualDetails.output_text}
              type="result"
              maxHeight="200px"
              projectId={projectId}
            />
          )}
        </Box>
      );
    }
    
    if ((step?.step_name || step?.step)?.includes('fixer') && actualDetails) {
      const fixDetails = actualDetails;
      return (
        <Box>
          <Box sx={{ 
            display: 'flex', 
            gap: 1.5, 
            mb: 2, 
            flexWrap: 'wrap',
            p: 1.5,
            bgcolor: '#f0fdf4',
            borderRadius: 1.5,
            border: '1px solid #bbf7d0'
          }}>
            <Box sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 0.5,
              px: 1.5,
              py: 0.5,
              bgcolor: '#dcfce7',
              borderRadius: 1,
              fontSize: '0.75rem',
              color: '#166534'
            }}>
              <EditIcon sx={{ fontSize: 14 }} />
              Total Fixes: {fixDetails.total_fixes || 0}
            </Box>
            {fixDetails.fixes_by_type && Object.entries(fixDetails.fixes_by_type).map(([type, count]) => (
              <Box key={type} sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 0.5,
                px: 1.5,
                py: 0.5,
                bgcolor: '#dcfce7',
                borderRadius: 1,
                fontSize: '0.75rem',
                color: '#166534'
              }}>
                {type}: {String(count)}
              </Box>
            ))}
          </Box>
          {fixDetails.fixes_summary && fixDetails.fixes_summary.length > 0 && (
            <SmartContentCard
              title={`Fix Details (${fixDetails.fixes_summary.length} fixes)`}
              content={fixDetails.fixes_summary.map((fix: any, index: number) => 
                `${index + 1}. Field: ${fix.attr} | Old value: "${fix.old}" → New value: "${fix.new}" | Type: ${fix.fix_type}`
              ).join('\n')}
              type="result"
              maxHeight="300px"
              projectId={projectId}
            />
          )}
        </Box>
      );
    }
    
    if (typeof detailsToRender === 'object' && (
        detailsToRender.segments_info || 
        detailsToRender.compression_ratio || 
        detailsToRender.segments_found !== undefined ||
        actualDetails?.segments_info ||
        actualDetails?.compression_ratio ||
        actualDetails?.segments_found !== undefined
      )) {
      const locatorDetails = actualDetails || detailsToRender;
      const segmentsInfo = locatorDetails.segments_info || [];
      
      return (
        <Box>
          <Box sx={{ 
            display: 'flex', 
            gap: 1.5, 
            mb: 2, 
            flexWrap: 'wrap',
            p: 1.5,
            bgcolor: '#f0f9ff',
            borderRadius: 1.5,
            border: '1px solid #bae6fd'
          }}>
            <Box sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 0.5,
              px: 1.5,
              py: 0.5,
              bgcolor: '#dbeafe',
              borderRadius: 1,
              fontSize: '0.75rem',
              color: '#1e40af'
            }}>
              📄 Original: {locatorDetails.original_length?.toLocaleString() || 'N/A'} chars
            </Box>
            <Box sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 0.5,
              px: 1.5,
              py: 0.5,
              bgcolor: '#dcfce7',
              borderRadius: 1,
              fontSize: '0.75rem',
              color: '#166534'
            }}>
              🎯 Segments: {locatorDetails.segments_found || 0}
            </Box>
            <Box sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 0.5,
              px: 1.5,
              py: 0.5,
              bgcolor: '#fef3c7',
              borderRadius: 1,
              fontSize: '0.75rem',
              color: '#92400e'
            }}>
              📊 Compression: {locatorDetails.compression_ratio || 'N/A'}
            </Box>
            <Box sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 0.5,
              px: 1.5,
              py: 0.5,
              bgcolor: '#e0e7ff',
              borderRadius: 1,
              fontSize: '0.75rem',
              color: '#3730a3'
            }}>
              🤖 Model: {locatorDetails.model || 'N/A'}
            </Box>
          </Box>
          {segmentsInfo.length > 0 && (
            <Box sx={{ mb: 2 }}>
              <Typography variant="subtitle2" sx={{ mb: 1.5, fontWeight: 600, color: '#374151', fontSize: '0.875rem' }}>
                📋 Located Segments ({segmentsInfo.length}):
              </Typography>
              <Box sx={{ 
                display: 'flex', 
                flexDirection: 'column', 
                gap: 1.5,
                maxHeight: '400px',
                overflowY: 'auto'
              }}>
                {segmentsInfo.map((segment: any, index: number) => (
                  <Box key={index} sx={{
                    p: 2,
                    bgcolor: '#f8fafc',
                    border: '1px solid #e2e8f0',
                    borderRadius: 1.5,
                    position: 'relative'
                  }}>
                    <Box sx={{ 
                      display: 'flex', 
                      justifyContent: 'space-between', 
                      alignItems: 'center',
                      mb: 1.5
                    }}>
                      <Typography variant="subtitle2" sx={{ 
                        fontWeight: 600, 
                        color: '#374151',
                        fontSize: '0.8rem'
                      }}>
                        Segment {index + 1}
                      </Typography>
                      <Box sx={{ display: 'flex', gap: 1 }}>
                        <Box sx={{
                          px: 1,
                          py: 0.25,
                          bgcolor: '#e0f2fe',
                          borderRadius: 0.5,
                          fontSize: '0.65rem',
                          color: '#0369a1'
                        }}>
                          {segment.length?.toLocaleString() || 0} chars
                        </Box>
                        <Box sx={{
                          px: 1,
                          py: 0.25,
                          bgcolor: '#f0fdf4',
                          borderRadius: 0.5,
                          fontSize: '0.65rem',
                          color: '#166534'
                        }}>
                          {((segment.relevance || 0) * 100).toFixed(1)}% relevance
                        </Box>
                      </Box>
                    </Box>
                    <Box sx={{
                      p: 1.5,
                      bgcolor: '#ffffff',
                      border: '1px solid #f1f5f9',
                      borderRadius: 1,
                      fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", monospace',
                      fontSize: '0.75rem',
                      color: '#475569',
                      lineHeight: 1.4,
                      maxHeight: '120px',
                      overflowY: 'auto'
                    }}>
                      <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                        {segment.preview || 'No preview available'}
                      </pre>
                    </Box>
                  </Box>
                ))}
              </Box>
            </Box>
          )}
        </Box>
      );
    }
    
    if (typeof detailsToRender === 'object' && (
        detailsToRender.document || 
        detailsToRender.extracted_rows !== undefined || 
        detailsToRender.model_used ||
        actualDetails?.document ||
        actualDetails?.extracted_rows !== undefined ||
        actualDetails?.model_used
      )) {
      return (
        <Box>
          {(detailsToRender.output_text || actualDetails?.output_text) && (
            <SmartContentCard
              title="Processing Result"
              content={detailsToRender.output_text || actualDetails?.output_text}
              type="result"
              maxHeight="200px"
              projectId={projectId}
            />
          )}
          {(detailsToRender.llm_input || actualDetails?.llm_input) && (
            <SmartContentCard
              title="Input"
              content={detailsToRender.llm_input || actualDetails?.llm_input}
              type="input"
              maxHeight="250px"
              projectId={projectId}
              isDocumentInput={true}
            />
          )}
          {(detailsToRender.llm_output || actualDetails?.llm_output) && (
            <SmartContentCard
              title="output"
              content={detailsToRender.llm_output || actualDetails?.llm_output}
              type="output"
              maxHeight="350px"
              projectId={projectId}
            />
          )}
        </Box>
      );
    }
    
    if (typeof details === 'object' && details.output_text && typeof details.output_text === 'string') {
      return (
        <SmartContentCard
          title="Output"
          content={details.output_text}
          type="output"
          maxHeight="400px"
          projectId={projectId}
        />
      );
    }
    
    if (typeof details === 'object' && details.data_preview) {
      const totalRows = details.data_preview.total_rows || 0;
      const hasData = totalRows > 0 && details.data_preview.data && details.data_preview.data.length > 0;
      
      return (
        <Box>
          <Box sx={{ 
            display: 'flex', 
            alignItems: 'center', 
            gap: 2, 
            mb: 2,
            p: 1.5,
            bgcolor: '#f8fafc',
            borderRadius: 1.5,
            border: '1px solid #e2e8f0'
          }}>
            <TableChartIcon sx={{ color: '#6b7280' }} />
            <Typography variant="subtitle2" sx={{ fontWeight: 600, color: '#374151' }}>
              Data Preview ({totalRows} rows)
            </Typography>
          </Box>
          
          {hasData ? (
            <SmartContentCard
              title="Preview Data"
              content={JSON.stringify(details.data_preview.data, null, 2)}
              type="result"
              maxHeight="300px"
              projectId={projectId}
            />
          ) : (
            <Box sx={{ 
              p: 3, 
              bgcolor: '#fefbf1',
              border: '1px solid #e2e8f0',
              borderRadius: 2,
              textAlign: 'center'
            }}>
              <Box sx={{ mb: 2, fontSize: '2rem' }}>⚠️</Box>
              <Typography variant="h6" sx={{ 
                color: '#6b7280', 
                fontWeight: 600,
                mb: 1,
                fontSize: '0.95rem'
              }}>
                No data extracted
              </Typography>
              <Typography variant="body2" sx={{ 
                color: '#9ca3af',
                fontSize: '0.8rem'
              }}>
                Possible causes: file is empty, format not supported, or content cannot be recognized
              </Typography>
            </Box>
          )}
        </Box>
      );
    }
    
    const content = typeof details === 'string' ? details : JSON.stringify(details, null, 2);
    if (content.trim()) {
      return (
        <SmartContentCard
          title="Details"
          content={content}
          type="result"
          maxHeight="300px"
          projectId={projectId}
        />
      );
    }
    
    return null;
  };

  return (
    <Box sx={{ width: '100%' }}>
      {(processing || hasRunningSteps) && (
        <Box sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 2,
          p: 2,
          mb: 3,
          bgcolor: '#f0f9ff',
          border: '1px solid #bfdbfe',
          borderRadius: 2,
          boxShadow: '0 1px 3px rgba(0, 0, 0, 0.1)'
        }}>
          <CircularProgress 
            size={24} 
            sx={{ color: '#0369a1' }} 
          />
          <Typography variant="body1" sx={{ 
            color: '#0369a1', 
            fontWeight: 600,
            fontSize: '0.95rem'
          }}>
            {hasRunningSteps ? 'Processing steps...' : 'Analyzing...'}
          </Typography>

        </Box>
      )}
      
      <Stack spacing={2} sx={{ width: '100%' }}>
        {filteredSteps?.map((step, index) => {
          const stepName = step.step_name || step.step || '';
          const stepTimestamp = step.timestamp || step.start_time || '';
          const uniqueStepId = `${stepName}_${stepTimestamp}_${index}`;
          const isExpanded = isStepExpanded(uniqueStepId);
          
          return (
            <Box key={uniqueStepId} sx={{
              position: 'relative',
              borderRadius: !isExpanded ? 1.5 : 2,
              overflow: 'hidden',
              boxShadow: !isExpanded ? '0 1px 2px rgba(0, 0, 0, 0.05)' : '0 1px 3px rgba(0, 0, 0, 0.1)',
              border: !isExpanded ? 'none' : `1px solid ${
                step.status === 'running' ? '#3b82f6' : 
                step.status === 'completed' ? '#10b981' :
                step.status === 'failed' ? '#ef4444' : '#e5e7eb'
              }`,
              bgcolor: !isExpanded ? '#f8f9fa' : 'white',
              transition: 'all 0.2s ease'
            }}
            >
              {isExpanded && (
                <Box sx={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  right: 0,
                  height: 3,
                  bgcolor: step.status === 'running' ? '#3b82f6' : 
                          step.status === 'completed' ? '#10b981' :
                          step.status === 'failed' ? '#ef4444' : '#f3f4f6'
                }} />
              )}
              
              {!isExpanded ? (
                <Box sx={{ 
                  p: 1.5,
                  display: 'flex', 
                  alignItems: 'center', 
                  gap: 1.5,
                  minHeight: '48px'
                }}>
                  <Box sx={{ flexShrink: 0 }}>
                    {getStepIcon(step, true)}
                  </Box>
                  <Box 
                    sx={{ flex: 1, minWidth: 0, cursor: 'pointer' }}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleStepExpansion(uniqueStepId);
                    }}
                  >
                    <Typography variant="body2" sx={{ 
                      fontWeight: 500,
                      color: '#374151',
                      fontSize: '0.875rem',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap'
                    }}>
                      {getStepDisplayName(stepName)}
                    </Typography>
                  </Box>
                  <Box sx={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 0.5,
                    px: 1,
                    py: 0.25,
                    borderRadius: 0.75,
                    bgcolor: step.status === 'running' ? '#f0f9ff' :
                            step.status === 'completed' ? 'white' :
                            step.status === 'failed' ? '#fef2f2' : '#f9fafb',
                    fontSize: '0.7rem',
                    fontWeight: 500,
                    color: step.status === 'running' ? '#0369a1' :
                           step.status === 'completed' ? '#166534' :
                           step.status === 'failed' ? '#dc2626' : '#6b7280'
                  }}>
                    {step.status === 'running' && <CircularProgress size={10} />}
                    <Typography sx={{ fontSize: '0.7rem' }}>
                      {step.status === 'running' ? 'Running' : 
                       step.status === 'completed' ? 'Finished' :
                       step.status === 'failed' ? 'Failed' : 'Waiting'}
                    </Typography>
                  </Box>
                  <IconButton 
                    size="small" 
                    sx={{ 
                      p: 0.5,
                      color: '#9ca3af',
                      '&:hover': {
                        bgcolor: '#f3f4f6'
                      }
                    }}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleStepExpansion(uniqueStepId);
                    }}
                  >
                    <ExpandMoreIcon sx={{ fontSize: 16 }} />
                  </IconButton>
                </Box>
              ) : (
                <Box sx={{ p: 2.5, pt: 3 }}>
                  <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 2.5 }}>
                    <Box sx={{ 
                      flexShrink: 0, 
                      mt: 0.5
                    }}>
                      {getStepIcon(step, false)}
                    </Box>
                    
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1.5 }}>
                        <Box 
                          sx={{ flex: 1, cursor: 'pointer' }}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleStepExpansion(uniqueStepId);
                          }}
                        >
                          <Typography variant="h6" sx={{ 
                            fontWeight: 600,
                            color: '#111827',
                            fontSize: '0.95rem',
                            mb: 0.5
                          }}>
                            {getStepDisplayName(stepName)}
                          </Typography>
                          {step.description && (
                            <Typography variant="body2" sx={{ 
                              fontSize: '0.8rem',
                              color: '#6b7280',
                              lineHeight: 1.4
                            }}>
                              {step.description}
                            </Typography>
                          )}
                        </Box>
                        
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <Box sx={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 0.5,
                            px: 1.5,
                            py: 0.5,
                            borderRadius: 1,
                            bgcolor: step.status === 'running' ? '#f0f9ff' :
                                    step.status === 'completed' ? '#f0fdf4' :
                                    step.status === 'failed' ? '#fef2f2' : '#f9fafb',
                            fontSize: '0.75rem',
                            fontWeight: 500,
                            color: step.status === 'running' ? '#0369a1' :
                                   step.status === 'completed' ? '#166534' :
                                   step.status === 'failed' ? '#dc2626' : '#6b7280'
                          }}>
                            {step.status === 'running' && <CircularProgress size={12} />}
                            <Typography sx={{ fontSize: '0.75rem' }}>
                              {step.status === 'running' ? 'Running' : 
                               step.status === 'completed' ? 'Finished' :
                               step.status === 'failed' ? 'Failed' : 'Waiting'}
                            </Typography>
                          </Box>
                          <IconButton 
                            size="small" 
                            sx={{ 
                              p: 0.5,
                              color: '#9ca3af',
                              '&:hover': {
                                bgcolor: '#f3f4f6'
                              }
                            }}
                            onClick={() => toggleStepExpansion(uniqueStepId)}
                          >
                            <ExpandLessIcon sx={{ fontSize: 16 }} />
                          </IconButton>
                        </Box>
                      </Box>
                      {step.error && (
                        <Box sx={{ 
                          p: 2, 
                          bgcolor: '#fef2f2',
                          border: '1px solid #fecaca',
                          borderRadius: 2,
                          color: '#991b1b',
                          fontSize: '0.875rem',
                          mb: 2
                        }}>
                          <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>
                            ❌ Error Message:
                          </Typography>
                          <Typography variant="body2">
                            {step.error}
                          </Typography>
                        </Box>
                      )}
                      {(step.result || step.details || step.llm_input || step.llm_output) && (
                        <Box sx={{ mt: 2 }}>
                          <Box sx={{ 
                            p: 2, 
                            bgcolor: '#f9fafb',
                            border: '1px solid #f3f4f6',
                            borderRadius: 1.5
                          }}>
                            {renderStepDetails(step.result || step.details, step)}
                          </Box>
                        </Box>
                      )}
                    </Box>
                  </Box>
                </Box>
              )}
            </Box>
          );
        })}
      </Stack>
    </Box>
  );
};

export default ProcessingSteps;



