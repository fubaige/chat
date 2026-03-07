-- 用户独立配置表
CREATE TABLE IF NOT EXISTS `user_settings` (
    `id`         INT          NOT NULL AUTO_INCREMENT,
    `user_id`    INT          NOT NULL,
    `key`        VARCHAR(100) NOT NULL,
    `value`      VARCHAR(2000) NOT NULL DEFAULT '',
    `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `ix_user_settings_user_id` (`user_id`),
    UNIQUE KEY `uq_user_settings_user_key` (`user_id`, `key`),
    CONSTRAINT `fk_user_settings_user`
        FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
