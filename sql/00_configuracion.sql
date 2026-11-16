CREATE SCHEMA IF NOT EXISTS workspace.riesgo_bronze COMMENT 'Datos crudos tal como llegan';
CREATE SCHEMA IF NOT EXISTS workspace.riesgo_silver COMMENT 'Datos limpios y deduplicados';
CREATE SCHEMA IF NOT EXISTS workspace.riesgo_gold   COMMENT 'Modelo dimensional para análisis';

CREATE VOLUME IF NOT EXISTS workspace.riesgo_bronze.aterrizaje
  COMMENT 'Archivos diarios del sistema fuente';

CREATE VOLUME IF NOT EXISTS workspace.riesgo_bronze.control
  COMMENT 'Checkpoints y esquemas de Auto Loader';