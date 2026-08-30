create database cbt;
use cbt;
CREATE TABLE USER (
    user_id INT PRIMARY KEY AUTO_INCREMENT,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) NOT NULL UNIQUE,
    mobile_no VARCHAR(15) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    dob DATE NOT NULL,
    gender ENUM('MALE','FEMALE','OTHER') NOT NULL,
    father_name VARCHAR(100) NOT NULL,
    address VARCHAR(255) NOT NULL,
    status ENUM('ACTIVE','BLOCKED') NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE BANK_BRANCH (
    branch_id INT PRIMARY KEY AUTO_INCREMENT,
    bank_name VARCHAR(100) NOT NULL,
    address VARCHAR(255) NOT NULL,
    ifsc_code VARCHAR(11) NOT NULL UNIQUE,
    status ENUM('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE'
);
CREATE TABLE ADMIN (
    admin_id INT PRIMARY KEY AUTO_INCREMENT,
    employee_id VARCHAR(50) NOT NULL UNIQUE,
    branch_id INT NOT NULL,
    admin_name VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('ADMIN','MANAGER','TELLER') NOT NULL DEFAULT 'ADMIN',
    status ENUM('ACTIVE','BLOCKED','INACTIVE') NOT NULL DEFAULT 'ACTIVE',
    FOREIGN KEY (branch_id) REFERENCES BANK_BRANCH(branch_id)
);
CREATE TABLE ACCOUNT_REQUEST (
    request_id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    aadhaar_number VARCHAR(12) NOT NULL UNIQUE,
    aadhaar_photo VARCHAR(255) NOT NULL,
    pan_number VARCHAR(10) NOT NULL UNIQUE,
    pan_photo VARCHAR(255) NOT NULL,
    status ENUM('PENDING','APPROVED','REJECTED') NOT NULL DEFAULT 'PENDING',
    submitted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_at TIMESTAMP NULL,
    FOREIGN KEY (user_id) REFERENCES USER(user_id)
);
CREATE TABLE BANK_ACCOUNT (
    account_id INT PRIMARY KEY AUTO_INCREMENT,
    account_number VARCHAR(20) NOT NULL UNIQUE,
    request_id INT NOT NULL UNIQUE,
    user_id INT NOT NULL,
    branch_id INT NOT NULL,
    account_type ENUM('SAVINGS','CURRENT') NOT NULL,
    account_status ENUM('ACTIVE','BLOCKED','CLOSED') NOT NULL DEFAULT 'ACTIVE',
    opened_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (request_id) REFERENCES ACCOUNT_REQUEST(request_id),
    FOREIGN KEY (user_id) REFERENCES USER(user_id),
    FOREIGN KEY (branch_id) REFERENCES BANK_BRANCH(branch_id)
);
ALTER TABLE USER
ADD COLUMN aadhaar_number VARCHAR(50) NOT NULL UNIQUE,
ADD COLUMN pan_number VARCHAR(50) NOT NULL UNIQUE,
ADD COLUMN aadhaar_photo VARCHAR(255) NOT NULL,
ADD COLUMN pan_photo VARCHAR(255) NOT NULL;
DROP TABLE ACCOUNT_REQUEST;
show tables;
drop table account_request;
SELECT COUNT(*) FROM BANK_ACCOUNT;
DROP TABLE BANK_ACCOUNT;
DROP TABLE ACCOUNT_REQUEST;
CREATE TABLE ACCOUNT_REQUEST (
    request_id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL UNIQUE,
    status ENUM('PENDING','APPROVED','REJECTED') NOT NULL DEFAULT 'PENDING',
    submitted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_at TIMESTAMP NULL,
    FOREIGN KEY (user_id) REFERENCES USER(user_id)
);
CREATE TABLE ACCOUNT (
    account_id INT PRIMARY KEY AUTO_INCREMENT,
    account_number VARCHAR(50) NOT NULL UNIQUE,
    user_id INT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status ENUM('ACTIVE','BLOCKED','CLOSED') NOT NULL DEFAULT 'ACTIVE',
    is_frozen BOOLEAN NOT NULL DEFAULT FALSE,
    FOREIGN KEY (user_id) REFERENCES USER(user_id)
);
CREATE TABLE TRANSACTION (
    transaction_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    reference_num VARCHAR(50) NOT NULL UNIQUE,
    account_id INT NOT NULL,
    transaction_type ENUM('DEPOSIT','WITHDRAW','TRANSFER') NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    transaction_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status ENUM('SUCCESS','FAILED','PENDING') NOT NULL DEFAULT 'SUCCESS',

    FOREIGN KEY (account_id) REFERENCES ACCOUNT(account_id)
);
CREATE TABLE FUND_TRANSFER (
    transfer_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    reference_num VARCHAR(50) NOT NULL UNIQUE,
    from_account_id INT NOT NULL,
    to_account_id INT NOT NULL,
    from_ifsc VARCHAR(50) NOT NULL,
    to_ifsc VARCHAR(50) NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    transfer_type ENUM('IMPS','NEFT','RTGS') NOT NULL,
    status ENUM('SUCCESS','FAILED','PENDING') NOT NULL DEFAULT 'SUCCESS',
    transfer_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (from_account_id) REFERENCES ACCOUNT(account_id),
    FOREIGN KEY (to_account_id) REFERENCES ACCOUNT(account_id)
);
CREATE TABLE OTP_VERIFICATION (
    otp_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    email VARCHAR(50) NOT NULL UNIQUE,
    otp_hash VARCHAR(255) NOT NULL,
    purpose ENUM('REGISTRATION','LOGIN','TRANSACTION') NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    attempts INT NOT NULL DEFAULT 0
);
show tables;
select * from admin;
USE cbt;

INSERT INTO ADMIN
(
    employee_id,
    branch_id,
    admin_name,
    email,
    password_hash,
    role,
    status
)
VALUES
(
    'EMP001',
    1,
    'System Administrator',
    'admin@corebanking.com',
    'scrypt:32768:8:1$sajVWfPgnfG1kko9$b21201c1a91a4ffaff8367021b93f7c95ddc7d4ca27146855e4588f6faba6f12cc46a6b0caa6ef784271eabe35cf1cf6973cf2f5ee528797ccd78789c32b6679',
    'ADMIN',
    'ACTIVE'
);

SELECT * FROM BANK_BRANCH;
INSERT INTO BANK_BRANCH
(
    bank_name,
    address,
    ifsc_code,
    status
)
VALUES
(
    'Core Banking Bank',
    'Hyderabad, Telangana',
    'CBTB0000001',
    'ACTIVE'
);
show tables;
desc account;
desc account_request;
select * from account_request;
USE cbt;
SELECT
    admin_id,
    employee_id,
    admin_name,
    email,
    role,
    status
FROM ADMIN;
desc transaction;
desc fund_transfer;
select * from transaction;
DESCRIBE ACCOUNT;
ALTER TABLE ACCOUNT
ADD COLUMN account_type VARCHAR(50) NOT NULL DEFAULT 'Savings Account';
ALTER TABLE ACCOUNT
ADD COLUMN account_type VARCHAR(50) NOT NULL DEFAULT 'Savings Account',
ADD COLUMN branch VARCHAR(100) DEFAULT 'Hyderabad Main',
ADD COLUMN ifsc_code VARCHAR(20) DEFAULT 'CORE0001234',
ADD COLUMN open_date DATE NULL;
ALTER TABLE ACCOUNT
ADD COLUMN branch VARCHAR(100) DEFAULT 'Hyderabad Main',
ADD COLUMN ifsc_code VARCHAR(20) DEFAULT 'CORE0001234',
ADD COLUMN open_date DATE NULL;
DESCRIBE ACCOUNT;