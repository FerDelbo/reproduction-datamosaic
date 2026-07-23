import React from 'react';
import {
  Box,
  Card,
  CardContent,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
  Chip,
  Alert,
  List,
  ListItem,
  ListItemText,
  Divider,
  Grid,
  Paper
} from '@mui/material';
import {
  TableChart as TableChartIcon,
  Warning as WarningIcon,
  Build as BuildIcon,
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
  Info as InfoIcon
} from '@mui/icons-material';

interface SnapshotData {
  run_id?: string;
  table?: string;
  table_name?: string; // Add possible field name
  table_id?: string;
  rows?: Array<{
    tuple_id: string;
    cells: {
      [key: string]: {
        best?: {
          value: string;
        };
        nbest?: any[];
        value?: string;
        evidences?: string[];
      };
    };
  }>;
  created_at?: string;
  processing_stage?: string;
  stage_description?: string;
}

interface ViolationData {
  id: string;
  table: string;
  tuple_id: string;
  attr: string;
  constraint_type: string;
  description: string;
  severity: 'error' | 'warn' | 'info';
  suggested_fix?: {
    value: any;
  };
  detector_id: string;
  timestamp: string;
}

interface FixData {
  id: string;
  table: string;
  tuple_id: string;
  attr: string;
  old: any;
  new: any;
  fix_type: string;
  applied_by: string;
  timestamp: string;
  fix_success: boolean;
  failure_reason?: string;
}

interface SnapshotsViewProps {
  snapshots: SnapshotData | SnapshotData[] | null;
}

export const SnapshotsView: React.FC<SnapshotsViewProps> = ({ snapshots }) => {
  if (!snapshots) {
    return <Alert severity="info">No snapshot data available</Alert>;
  }

  const snapshotList = Array.isArray(snapshots) ? snapshots : [snapshots];
  
  const validSnapshots = snapshotList.filter(snapshot => snapshot && typeof snapshot === 'object');

  if (validSnapshots.length === 0) {
    return <Alert severity="info">Snapshot data format is invalid or empty</Alert>;
  }

  return (
    <Box>
      {validSnapshots.map((snapshot, index) => (
        <Card key={index} sx={{ mb: 2 }}>
          <CardContent>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
              <TableChartIcon color="primary" sx={{ mr: 1 }} />
              <Typography variant="h6" component="div">
                Table: {snapshot.table || snapshot.table_name || 'Unknown Table'}
              </Typography>
              {snapshot.processing_stage && (
                <Chip 
                  label={snapshot.processing_stage} 
                  size="small" 
                  color="primary" 
                  sx={{ ml: 2 }}
                />
              )}
            </Box>
            
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Run ID: {snapshot.run_id || 'Unknown'}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Created time: {snapshot.created_at ? new Date(snapshot.created_at).toLocaleString('en-US') : 'Unknown time'}
            </Typography>
            {snapshot.stage_description && (
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                {snapshot.stage_description}
              </Typography>
            )}

            {!snapshot.rows || snapshot.rows.length === 0 ? (
              <Alert severity="info" sx={{ mt: 2 }}>
                This snapshot has no data rows
              </Alert>
            ) : (
              <>
                <TableContainer component={Paper} sx={{ maxHeight: '60vh', overflow: 'auto' }}>
                  <Table stickyHeader size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Row ID</TableCell>
                        {(() => {
                          const firstRowCells = snapshot.rows[0].cells;
                          const fieldOrder = Object.keys(firstRowCells);
                          return fieldOrder.map((attr) => (
                            <TableCell key={attr}>{attr}</TableCell>
                          ));
                        })()}
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {(() => {
                        const fieldOrder = snapshot.rows.length > 0 ? Object.keys(snapshot.rows[0].cells) : [];
                        
                        return snapshot.rows.map((row) => (
                          <TableRow key={row.tuple_id} hover>
                            <TableCell component="th" scope="row">
                              {row.tuple_id}
                            </TableCell>
                            {fieldOrder.map((attr) => {
                              const cell = row.cells[attr];
                              return (
                                <TableCell key={attr}>
                                  <Box>
                                    <Typography variant="body2">
                                      {cell?.best?.value ?? cell?.value ?? 'N/A'}
                                    </Typography>
                                    {cell?.evidences && cell.evidences.length > 0 && (
                                      <Typography variant="caption" color="text.secondary">
                                        {cell.evidences.join(', ')}
                                      </Typography>
                                    )}
                                  </Box>
                                </TableCell>
                              );
                            })}
                          </TableRow>
                        ));
                      })()}
                    </TableBody>
                  </Table>
                </TableContainer>

                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  Total: {snapshot.rows.length} rows of data
                </Typography>
              </>
            )}
          </CardContent>
        </Card>
      ))}
    </Box>
  );
};

interface ViolationsViewProps {
  violations: ViolationData[] | { [table: string]: ViolationData[] } | null;
}

export const ViolationsView: React.FC<ViolationsViewProps> = ({ violations }) => {
  if (!violations) {
    return <Alert severity="info">No violation data</Alert>;
  }

  const getSeverityIcon = (severity: string) => {
    switch (severity) {
      case 'error':
        return <ErrorIcon color="error" />;
      case 'warn':
        return <WarningIcon color="warning" />;
      case 'info':
        return <InfoIcon color="info" />;
      default:
        return <InfoIcon color="info" />;
    }
  };

  const getSeverityColor = (severity: string): "error" | "warning" | "info" => {
    switch (severity) {
      case 'error':
        return 'error';
      case 'warn':
        return 'warning';
      case 'info':
        return 'info';
      default:
        return 'info';
    }
  };

  const renderViolationList = (violationList: ViolationData[], title?: string) => (
    <Card sx={{ mb: 2 }}>
      <CardContent>
        {title && (
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
            <WarningIcon color="warning" sx={{ mr: 1 }} />
            <Typography variant="h6">
              Table: {title}
            </Typography>
          </Box>
        )}
        
        <List>
          {violationList.map((violation, index) => (
            <React.Fragment key={violation.id}>
              <ListItem alignItems="flex-start">
                <Box sx={{ display: 'flex', alignItems: 'flex-start', width: '100%' }}>
                  <Box sx={{ mr: 2, mt: 0.5 }}>
                    {getSeverityIcon(violation.severity)}
                  </Box>
                  <Box sx={{ flex: 1 }}>
                    <ListItemText
                      primary={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <Typography variant="subtitle2">
                            {violation.attr} - {violation.constraint_type}
                          </Typography>
                          <Chip 
                            label={violation.severity}
                            size="small"
                            color={getSeverityColor(violation.severity)}
                          />
                        </Box>
                      }
                      secondary={
                        <Box>
                          <Typography variant="body2" sx={{ mb: 1 }}>
                            {violation.description}
                          </Typography>
                          <Grid container spacing={1}>
                            <Grid item xs={6}>
                              <Typography variant="caption" color="text.secondary">
                                Row ID: {violation.tuple_id}
                              </Typography>
                            </Grid>
                            <Grid item xs={6}>
                              <Typography variant="caption" color="text.secondary">
                                Verifier: {violation.detector_id}
                              </Typography>
                            </Grid>
                            <Grid item xs={12}>
                              <Typography variant="caption" color="text.secondary">
                                Time: {new Date(violation.timestamp).toLocaleString('en-US')}
                              </Typography>
                            </Grid>
                          </Grid>
                          {violation.suggested_fix && (
                            <Box sx={{ mt: 1, p: 1, bgcolor: 'grey.50', borderRadius: 1 }}>
                              <Typography variant="caption" color="primary">
                                Suggested fix: {JSON.stringify(violation.suggested_fix.value)}
                              </Typography>
                            </Box>
                          )}
                        </Box>
                      }
                    />
                  </Box>
                </Box>
              </ListItem>
              {index < violationList.length - 1 && <Divider />}
            </React.Fragment>
          ))}
        </List>
        
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          Total: {violationList.length} violations
        </Typography>
      </CardContent>
    </Card>
  );

  if (Array.isArray(violations)) {
    return <Box>{renderViolationList(violations)}</Box>;
  } else {
    return (
      <Box>
        {Object.entries(violations).map(([table, violationList]) => (
          <div key={table}>
            {renderViolationList(violationList, table)}
          </div>
        ))}
      </Box>
    );
  }
};

interface FixesViewProps {
  fixes: FixData[] | { [table: string]: FixData[] } | null;
}

export const FixesView: React.FC<FixesViewProps> = ({ fixes }) => {
  if (!fixes) {
    return <Alert severity="info">No fix data</Alert>;
  }

  const getFixStatusIcon = (success: boolean) => {
    return success ? <CheckCircleIcon color="success" /> : <ErrorIcon color="error" />;
  };

  const renderFixList = (fixList: FixData[], title?: string) => (
    <Card sx={{ mb: 2 }}>
      <CardContent>
        {title && (
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
            <BuildIcon color="primary" sx={{ mr: 1 }} />
            <Typography variant="h6">
              Table: {title}
            </Typography>
          </Box>
        )}
        
        <List>
          {fixList.map((fix, index) => (
            <React.Fragment key={fix.id}>
              <ListItem alignItems="flex-start">
                <Box sx={{ display: 'flex', alignItems: 'flex-start', width: '100%' }}>
                  <Box sx={{ mr: 2, mt: 0.5 }}>
                    {getFixStatusIcon(fix.fix_success)}
                  </Box>
                  <Box sx={{ flex: 1 }}>
                    <ListItemText
                      primary={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <Typography variant="subtitle2">
                            {fix.attr} - {fix.fix_type}
                          </Typography>
                          <Chip 
                            label={fix.fix_success ? 'Success' : 'Failed'}
                            size="small"
                            color={fix.fix_success ? 'success' : 'error'}
                          />
                        </Box>
                      }
                      secondary={
                        <Box>
                          <Grid container spacing={1} sx={{ mb: 1 }}>
                            <Grid item xs={6}>
                              <Typography variant="caption" color="text.secondary">
                                Original value: {JSON.stringify(fix.old)}
                              </Typography>
                            </Grid>
                            <Grid item xs={6}>
                              <Typography variant="caption" color="text.secondary">
                                New value: {JSON.stringify(fix.new)}
                              </Typography>
                            </Grid>
                          </Grid>
                          <Grid container spacing={1}>
                            <Grid item xs={4}>
                              <Typography variant="caption" color="text.secondary">
                                Row ID: {fix.tuple_id}
                              </Typography>
                            </Grid>
                            <Grid item xs={4}>
                              <Typography variant="caption" color="text.secondary">
                                Applied by: {fix.applied_by}
                              </Typography>
                            </Grid>
                            <Grid item xs={4}>
                              <Typography variant="caption" color="text.secondary">
                                Time: {new Date(fix.timestamp).toLocaleString('en-US')}
                              </Typography>
                            </Grid>
                          </Grid>
                          {!fix.fix_success && fix.failure_reason && (
                            <Box sx={{ mt: 1, p: 1, bgcolor: 'error.50', borderRadius: 1 }}>
                              <Typography variant="caption" color="error.main">
                                Failure reason: {fix.failure_reason}
                              </Typography>
                            </Box>
                          )}
                        </Box>
                      }
                    />
                  </Box>
                </Box>
              </ListItem>
              {index < fixList.length - 1 && <Divider />}
            </React.Fragment>
          ))}
        </List>
        
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          Total: {fixList.length} fixes
        </Typography>
      </CardContent>
    </Card>
  );

  if (Array.isArray(fixes)) {
    return <Box>{renderFixList(fixes)}</Box>;
  } else {
    return (
      <Box>
        {Object.entries(fixes).map(([table, fixList]) => (
          <div key={table}>
            {renderFixList(fixList, table)}
          </div>
        ))}
      </Box>
    );
  }
};
