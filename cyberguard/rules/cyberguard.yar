
rule CG_Ransomware_Marker {
    meta:
        description = "Generic ransomware file extension change marker"
        severity = "critical"
    strings:
        $ext1 = ".locked" ascii
        $ext2 = ".encrypted" ascii
        $ext3 = ".crypted" ascii
        $ransom1 = "YOUR FILES HAVE BEEN ENCRYPTED" ascii nocase
        $ransom2 = "send bitcoin" ascii nocase
        $ransom3 = "recovery key" ascii nocase
    condition:
        (any of ($ext*)) and (any of ($ransom*))
}

rule CG_CryptoMiner_XMRig {
    meta:
        description = "XMRig or similar Monero miner"
        severity = "critical"
    strings:
        $s1 = "stratum+tcp://" ascii
        $s2 = "xmrig" ascii nocase
        $s3 = "mining.subscribe" ascii
        $s4 = "donate-level" ascii
    condition:
        2 of them
}

rule CG_TraderTraitor_Backdoor {
    meta:
        description = "TraderTraitor/Lazarus Group backdoor patterns (FLATROOF/ROOFDECK)"
        severity = "critical"
        source = "SentinelOne public IOCs, Sept 2026"
    strings:
        $s1 = "FLATROOF" ascii nocase
        $s2 = "ROOFDECK" ascii nocase
        $s3 = "gaslight" ascii nocase
        $s4 = { 6A 40 68 00 30 00 00 6A 14 6A 00 }  // shellcode stub
        $c2_pattern = /https?:\/\/[a-z0-9]{8,16}\.(xyz|top|click)\/[a-z0-9]{4,8}/ ascii
    condition:
        any of ($s*) or $c2_pattern
}

rule CG_PromptInjection_File {
    meta:
        description = "Prompt injection payload stored in file"
        severity = "high"
    strings:
        $inj1 = "ignore previous instructions" ascii nocase
        $inj2 = "you are now DAN" ascii nocase
        $inj3 = "new system prompt:" ascii nocase
        $inj4 = "disregard all rules" ascii nocase
        $inj5 = "IGNORE ALL PREVIOUS" ascii
    condition:
        any of them
}

rule CG_Webshell_Generic {
    meta:
        description = "Generic web shell detection"
        severity = "critical"
    strings:
        $php1 = "eval(base64_decode(" ascii
        $php2 = "system($_GET[" ascii
        $php3 = "passthru($_POST[" ascii
        $py1 = "exec(request.form[" ascii
        $py2 = "__import__('os').system(" ascii
    condition:
        any of them
}

rule CG_EIP7702_Sweeper {
    meta:
        description = "EIP-7702 wallet sweeper contract bytecode marker"
        severity = "critical"
        reference = "Binance hack Oct 2026 — fireblocks.com/blog/binance-hack-eip-7702"
    strings:
        // EIP-7702 delegation prefix: 0xef 0x01 0x00 followed by address
        $delegation = { EF 01 00 }
        // Common sweeper pattern: PUSH20 (address) + CALL/SELFDESTRUCT
        $sweeper = { 73 ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? ?? FF }
    condition:
        $delegation or $sweeper
}
