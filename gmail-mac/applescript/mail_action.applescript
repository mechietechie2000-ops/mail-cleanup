-- mail_action.applescript
--
-- Generalized Mail.app cleanup script. Called as:
--
--   osascript mail_action.applescript <email_id> <log_file> <batch_size> <mode> <action> <data>
--
-- All dynamic values (sender lists, display names, subjects, day thresholds)
-- arrive as argv items instead of being spliced into the script text, so a
-- stray quote or backslash in a subject/sender can't break the script.
--
-- mode is one of:
--   sender                      data = "addr1<RS>addr2<RS>..."
--   display_name                data = "Name One<RS>Name Two<RS>..."
--   from_subject                data = "sender<FS>subject<RS>sender2<FS>subject2"
--   display_name_days           data = "Name<FS>daysAgo<RS>Name2<FS>daysAgo2"
--   display_name_days_subject   data = "Name<FS>daysAgo<FS>subject<RS>..."
--
-- <RS> (record separator) and <FS> (field separator) are ASCII control
-- characters 30 and 31 - not printable, so they can never collide with a
-- real sender address, display name, or subject line.
--
-- action is "delete" or "list" (list = log matches only, don't delete)

on run argv
    set theEmailId to item 1 of argv
    set theLogFile to item 2 of argv
    set theBatchSize to (item 3 of argv) as integer
    set theMode to item 4 of argv
    set theAction to item 5 of argv
    set theData to ""
    if (count of argv) >= 6 then set theData to item 6 of argv

    set RS to ASCII character 30
    set FS to ASCII character 31

    set recordList to {}
    if theData is not "" then
        set recordList to my splitString(theData, RS)
    end if

    set theAccount to missing value
    if theEmailId is "" then
        tell application "Mail" to set theAccount to item 1 of accounts
    else
        set theAccount to my findAccountByEmail(theEmailId)
        if theAccount is missing value then
            error "ACCOUNT_NOT_FOUND: " & theEmailId
        end if
    end if

    set matchCount to 0
    set counter to 0

    with timeout of 600 seconds
        tell application "Mail"
            set theMailbox to mailbox "INBOX" of theAccount
            set theMessages to messages of theMailbox

            repeat with msg in theMessages
                if counter is greater than or equal to theBatchSize then exit repeat
                set counter to counter + 1

                set msgSubject to subject of msg
                set msgSender to sender of msg
                set senderEmail to extract address from msgSender
                set msgDisplayName to extract name from msgSender
                set msgDateReceived to date received of msg

                set isMatch to my messageMatches(theMode, recordList, FS, senderEmail, msgDisplayName, msgSubject, msgDateReceived)

                if isMatch then
                    set matchCount to matchCount + 1
                    set msgEntry to "[" & (msgDateReceived as text) & "] " & senderEmail & " | " & msgSubject
                    my appendToLog(theLogFile, msgEntry)
                    log msgEntry
                    if theAction is "delete" then
                        --delete msg
                        log msg 
                    end if
                end if
            end repeat
        end tell
    end timeout

    set summary to "Processed " & counter & " messages, " & matchCount & " matched, action=" & theAction
    log summary
    return summary
end run

-- ---------------------------------------------------------------------------
-- Matching logic, one branch per mode
-- ---------------------------------------------------------------------------
on messageMatches(theMode, recordList, FS, senderEmail, msgDisplayName, msgSubject, msgDateReceived)
    if theMode is "sender" then
        repeat with rec in recordList
            if senderEmail is (rec as text) then return true
        end repeat
        return false

    else if theMode is "display_name" then
        repeat with rec in recordList
            if msgDisplayName is (rec as text) then return true
        end repeat
        return false

    else if theMode is "from_subject" then
        repeat with rec in recordList
            set fields to my splitString(rec as text, FS)
            if (count of fields) is 2 then
                set theSender to item 1 of fields
                set theSubject to item 2 of fields
                if senderEmail is theSender and msgSubject contains theSubject then return true
            end if
        end repeat
        return false

    else if theMode is "display_name_days" then
        repeat with rec in recordList
            set fields to my splitString(rec as text, FS)
            if (count of fields) is 2 then
                set theName to item 1 of fields
                set theDays to (item 2 of fields) as integer
                set cutoffDate to (current date) - (theDays * days)
                if msgDisplayName is theName and msgDateReceived < cutoffDate then return true
            end if
        end repeat
        return false

    else if theMode is "display_name_days_subject" then
        repeat with rec in recordList
            set fields to my splitString(rec as text, FS)
            if (count of fields) is 3 then
                set theName to item 1 of fields
                set theDays to (item 2 of fields) as integer
                set theSubject to item 3 of fields
                set cutoffDate to (current date) - (theDays * days)
                if msgDisplayName is theName and msgDateReceived < cutoffDate and msgSubject contains theSubject then return true
            end if
        end repeat
        return false
    end if

    return false
end messageMatches

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------
on findAccountByEmail(theEmailId)
    tell application "Mail"
        repeat with acc in accounts
            try
                if theEmailId is in (email addresses of acc) then return acc
            on error errMsg
                log "Error checking account emails: " & errMsg
            end try
        end repeat
    end tell
    return missing value
end findAccountByEmail

on appendToLog(theLogFile, theText)
    try
        set fileRef to open for access theLogFile with write permission
        write theText & return to fileRef starting at eof
        close access fileRef
    on error errMsg
        log "Error writing to log file: " & errMsg
        try
            close access fileRef
        end try
    end try
end appendToLog

on splitString(theString, theDelimiter)
    set oldDelims to AppleScript's text item delimiters
    set AppleScript's text item delimiters to theDelimiter
    set theList to text items of theString
    set AppleScript's text item delimiters to oldDelims
    return theList
end splitString
