-- export_recent_messages.applescript
--
-- Pulls the most recent N messages from an account's INBOX for manual
-- review BEFORE deciding who to add to a delete/block list. Read-only -
-- never deletes anything.
--
-- Usage:
--   osascript export_recent_messages.applescript <email_id> <count> <max_body_chars>
--
-- <email_id> may be "" to just use the first Mail account.
-- <max_body_chars> is an approximate cap (default 4000) - the AppleScript
-- side only needs to grab "enough" of the body; Python does the precise
-- 200-word truncation afterwards.
--
-- Output: one line to stdout per message, fields separated by ASCII 31
-- (unit separator), records separated by ASCII 30 (record separator):
--   messageId <FS> senderEmail <FS> dateReceived <FS> subject <FS> bodySnippet

on run argv
    set theEmailId to item 1 of argv
    set theCount to (item 2 of argv) as integer
    set theMaxChars to 4000
    if (count of argv) >= 3 then set theMaxChars to (item 3 of argv) as integer

    set RS to ASCII character 30
    set FS to ASCII character 31

    set theAccount to missing value
    if theEmailId is "" then
        tell application "Mail" to set theAccount to item 1 of accounts
    else
        set theAccount to my findAccountByEmail(theEmailId)
        if theAccount is missing value then
            error "ACCOUNT_NOT_FOUND: " & theEmailId
        end if
    end if

    set outputParts to {}
    set counter to 0

    with timeout of 600 seconds
        tell application "Mail"
            set theMailbox to mailbox "INBOX" of theAccount
            set theMessages to messages of theMailbox

            repeat with msg in theMessages
                if counter is greater than or equal to theCount then exit repeat
                set counter to counter + 1

                set msgId to id of msg
                set msgSubject to subject of msg
                set msgSender to sender of msg
                set senderEmail to extract address from msgSender
                set msgDateReceived to (date received of msg) as text

                set msgBody to ""
                try
                    set msgBody to (content of msg) as text
                on error
                    set msgBody to "(could not read body)"
                end try

                if (length of msgBody) > theMaxChars then
                    set msgBody to (text 1 thru theMaxChars of msgBody)
                end if

                -- flatten newlines/tabs so one record stays one line
                set msgBody to my flattenWhitespace(msgBody)
                set msgSubject to my flattenWhitespace(msgSubject)

                set theRecord to (msgId as text) & FS & senderEmail & FS & msgDateReceived & FS & msgSubject & FS & msgBody
                set end of outputParts to theRecord
            end repeat
        end tell
    end timeout

    set oldDelims to AppleScript's text item delimiters
    set AppleScript's text item delimiters to RS
    set outputText to outputParts as text
    set AppleScript's text item delimiters to oldDelims
    return outputText
end run

on flattenWhitespace(theText)
    set oldDelims to AppleScript's text item delimiters
    repeat with ch in {(ASCII character 10), (ASCII character 13), (ASCII character 9)}
        set AppleScript's text item delimiters to (ch as text)
        set theItems to text items of theText
        set AppleScript's text item delimiters to " "
        set theText to theItems as text
    end repeat
    set AppleScript's text item delimiters to oldDelims
    return theText
end flattenWhitespace

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
