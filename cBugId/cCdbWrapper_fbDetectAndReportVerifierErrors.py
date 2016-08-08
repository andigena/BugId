import re;
from cBugReport import cBugReport;
from fsGetNumberDescription import fsGetNumberDescription;
from fsGetOffsetDescription import fsGetOffsetDescription;

def cCdbWrapper_fbDetectAndReportVerifierErrors(oCdbWrapper, asCdbOutput):
  uErrorNumber = None;
  uProcessId = None;
  sMessage = None;
  uHeapBlockAddress = None;
  uHeapBlockSize = None;
  uCorruptedStamp = None;
  for sLine in asCdbOutput:
    # Ignore exmpty lines
    if not sLine:
      continue;
    # Look for the first VERIFIER STOP message and gather information
    if uErrorNumber is None:
      oErrorMessageMatch = re.match(r"^VERIFIER STOP ([0-9A-F]+): pid 0x([0-9A-F]+): (.*?)\s*$", sLine);
      if oErrorMessageMatch:
        print "*** Detected heap verifier error ".ljust(120, "*");
        sErrorNumber, sProcessId, sMessage = oErrorMessageMatch.groups();
        uErrorNumber = long(sErrorNumber, 16);
        uProcessId = long(sProcessId, 16);
      continue;
    # A VERIFIER STOP message has been detected, gather what information verifier provides:
    oInformationMatch = re.match(r"\t([0-9A-F]+) : (.*?)\s*$", sLine);
    if oInformationMatch:
      sValue, sDescription = oInformationMatch.groups();
      uValue = long(sValue, 16);
      if sDescription == "Heap block": uHeapBlockAddress = uValue;
      elif sDescription == "Block size": uHeapBlockSize = uValue;
      elif sDescription == "Corrupted stamp": uCorruptedStamp = uValue;
      continue;
    # End of VERIFIER STOP message; report a bug.
    uCorruptionAddress = None;
    if sMessage == "corrupted start stamp":
      # A bug in verifier causes a corruption of the end stamp to be reported as a corruption of the start stamp, so
      # we're going to have to check both:
      uPointerSize = oCdbWrapper.fuGetValue("$ptrsize");
      if not oCdbWrapper.bCdbRunning: return;
      # https://msdn.microsoft.com/en-us/library/ms220938(v=vs.90).aspx
      uEndStampAddress = uHeapBlockAddress - 4;                     # ULONG
      uEndStamp = oCdbWrapper.fuGetValue("dwo(0x%X)" % uEndStampAddress);
      if uPointerSize == 8:
        uEndStampPaddingAddress = uEndStampAddress - 4;             # Alignment for next ULONG (end stamp)
        uEndStampPadding = oCdbWrapper.fuGetValue("dwo(0x%X)" % uEndStampPaddingAddress);
      else:
        uEndStampPaddingAddress = uEndStampAddress;
        uEndStampPadding = None;
      uStackTraceAddress = uEndStampPaddingAddress - uPointerSize;  # PVOID
      uFreeQueueAddress = uStackTraceAddress - 2 * uPointerSize;    # LIST_ENTRY
      uActualSizeAddress = uFreeQueueAddress - uPointerSize;        # size_t
      uRequestedSizeAddress = uActualSizeAddress - uPointerSize;    # size_t
      uHeapAddressAddress = uRequestedSizeAddress - uPointerSize;   # PVOID
      if uPointerSize == 8:
        uStartStampPaddingAddress = uHeapAddressAddress - 4;        # Alignment for previous ULONG (start stamp)
        uStartStampPadding = oCdbWrapper.fuGetValue("dwo(0x%X)" % uStartStampPaddingAddress);
      else:
        uStartStampPaddingAddress = uHeapAddressAddress;
        uStartStampPadding = None;
      uStartStampAddress = uStartStampPaddingAddress - 4;           # ULONG
      uStartStamp = oCdbWrapper.fuGetValue("dwo(0x%X)" % uStartStampAddress);
      for (uAddress, uValue, uSize, auExpectedValues) in [
        (uStartStampAddress,        uStartStamp,        4, [0xABCDBBBA, 0xABCDBBBB]),
        (uStartStampPaddingAddress, uStartStampPadding, 4, [None, 0]),
        (uEndStampPaddingAddress,   uEndStampPadding,   4, [None, 0]),
        (uEndStampAddress,          uEndStamp,          4, [0xDCBABBBA, 0xDCBABBBB]),
      ]:
        # See if the value is expected
        if uValue not in auExpectedValues:
          # Find the value that has the highest offset for its first corruption
          uHighestCorruptionOffset = 0;
          for uExpectedValue in auExpectedValues:
            if uExpectedValue is None: continue;
            for uCorruptionOffset in xrange(uSize):
              uMask = 0xFF << (8 * uCorruptionOffset);
              if uValue & uMask != uExpectedValue & uMask:
                if uCorruptionOffset > uHighestCorruptionOffset:
                  uHighestCorruptionOffset = uCorruptionOffset;
                break;
          uCorruptionAddress = uAddress + uHighestCorruptionOffset;
          break;
      else:
        raise AssertionError("Cannot find any sign of corruption");
    if uCorruptionAddress is not None:
      sMessage = "heap corruption";
      uCorruptionOffset = uCorruptionAddress - uHeapBlockAddress;
      if uCorruptionOffset > uHeapBlockSize:
        uCorruptionOffset -= uHeapBlockSize;
        sOffsetDescription = "%d/0x%X bytes beyond" % (uCorruptionOffset, uCorruptionOffset);
      else:
        assert uCorruptionOffset < 0, "Page heap unexpectedly detected corruption inside a heap block!?";
        sOffsetDescription = "%d/0x%X bytes before" % (-uCorruptionOffset, -uCorruptionOffset);
      sBugTypeId = "HeapCorrupt:OOB[%s]%s" % (fsGetNumberDescription(uHeapBlockSize), fsGetOffsetDescription(uCorruptionOffset));
      sBugDescription = "Page heap detected %s at 0x%X; %s a %d/0x%X byte heap block at address 0x%X" % \
          (sMessage, uCorruptionAddress, sOffsetDescription, uHeapBlockSize, uHeapBlockSize, uHeapBlockAddress);
      uRelevantAddress = uCorruptionAddress;
    else:
      sBugTypeId = "HeapCorrupt:???[%s]" % fsGetNumberDescription(uHeapBlockSize);
      sBugDescription = "Page heap detected %s in a %d/0x%X byte heap block at address 0x%X." % \
          (sMessage, uHeapBlockSize, uHeapBlockSize, uHeapBlockAddress);
      uRelevantAddress = uHeapBlockAddress;
    sSecurityImpact = "Potentially exploitable security issue, if the corruption is attacker controlled";
    oCdbWrapper.oBugReport = cBugReport.foCreate(oCdbWrapper, sBugTypeId, sBugDescription, sSecurityImpact);
    oCdbWrapper.oBugReport.auRelevantAddresses.append(uRelevantAddress);
    return True;
  return False;
