# Win32 & UIAutomation helper script for Power BI Desktop session operations
param(
    [Parameter(Mandatory=$true)][string]$Action,
    [int]$TargetPid = 0,
    [string]$PageName = "",
    [string]$OutPath = "",
    [string]$SrcPng = "",
    [string]$DstRgba = "",
    [string]$CropOut = "",
    [int]$CropX = 0,
    [int]$CropY = 0,
    [int]$CropW = 0,
    [int]$CropH = 0,
    [int]$Scale = 1
)

$ErrorActionPreference = "Stop"

if ($Action -eq "NavigatePage") {
    try {
        Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes -ErrorAction SilentlyContinue
        $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $TargetPid)
        $win = [System.Windows.Automation.AutomationElement]::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
        if ($win) {
            $tabCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::TabItem)
            $tabs = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tabCond)
            $found = $null
            foreach ($tab in $tabs) {
                if ($tab.Current.Name -eq $PageName -or $tab.Current.AutomationId -eq $PageName) {
                    $found = $tab
                    break
                }
            }
            if ($found) {
                $selPattern = $found.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
                if ($selPattern) {
                    $selPattern.Select()
                } else {
                    $invPattern = $found.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
                    if ($invPattern) { $invPattern.Invoke() }
                }
                [PSCustomObject]@{ ok = $true; navigated = $true; page = $PageName; method = "uia" } | ConvertTo-Json -Compress
                exit 0
            }
        }
        [PSCustomObject]@{ ok = $true; navigated = $false; page = $PageName; method = "fallback" } | ConvertTo-Json -Compress
    } catch {
        [PSCustomObject]@{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
        exit 1
    }
    exit 0
}

if ($Action -eq "CaptureWindow") {
    try {
        Add-Type @"
        using System;
        using System.Runtime.InteropServices;
        using System.Drawing;

        public class Win32Capture {
            [DllImport("user32.dll")]
            public static extern bool PrintWindow(IntPtr hwnd, IntPtr hdcBlt, uint nFlags);

            [DllImport("user32.dll")]
            public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

            [DllImport("user32.dll")]
            public static extern uint GetDpiForWindow(IntPtr hwnd);

            [StructLayout(LayoutKind.Sequential)]
            public struct RECT {
                public int Left;
                public int Top;
                public int Right;
                public int Bottom;
            }
        }
"@ -ReferencedAssemblies System.Drawing

        $p = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
        if (-not $p) {
            [PSCustomObject]@{ ok = $false; error = "process $TargetPid not found" } | ConvertTo-Json -Compress
            exit 1
        }
        $hWnd = $p.MainWindowHandle
        if ($hWnd -eq [IntPtr]::Zero) {
            [PSCustomObject]@{ ok = $false; error = "no main window handle for pid $TargetPid" } | ConvertTo-Json -Compress
            exit 1
        }
        $rect = New-Object Win32Capture+RECT
        [Win32Capture]::GetWindowRect($hWnd, [ref]$rect)
        $w = [Math]::Max(1, $rect.Right - $rect.Left)
        $h = [Math]::Max(1, $rect.Bottom - $rect.Top)
        $dpi = 96
        try {
            $dpiVal = [Win32Capture]::GetDpiForWindow($hWnd)
            if ($dpiVal -gt 0) { $dpi = $dpiVal }
        } catch {}

        $bmp = New-Object System.Drawing.Bitmap($w, $h)
        $gfx = [System.Drawing.Graphics]::FromImage($bmp)
        $hdc = $gfx.GetHdc()
        # PW_RENDERFULLCONTENT = 2
        $success = [Win32Capture]::PrintWindow($hWnd, $hdc, 2)
        $gfx.ReleaseHdc($hdc)
        $gfx.Dispose()

        if (-not $success) {
            $gfx2 = [System.Drawing.Graphics]::FromImage($bmp)
            $hdc2 = $gfx2.GetHdc()
            [Win32Capture]::PrintWindow($hWnd, $hdc2, 0)
            $gfx2.ReleaseHdc($hdc2)
            $gfx2.Dispose()
        }

        $outDir = [System.IO.Path]::GetDirectoryName($OutPath)
        if ($outDir -and -not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
        $bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
        $bmp.Dispose()
        [PSCustomObject]@{ ok = $true; path = $OutPath; width = $w; height = $h; dpi = $dpi; via = "printwindow" } | ConvertTo-Json -Compress
    } catch {
        [PSCustomObject]@{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
        exit 1
    }
    exit 0
}

if ($Action -eq "CropImage") {
    try {
        Add-Type -AssemblyName System.Drawing
        if (-not (Test-Path $SrcPng)) {
            [PSCustomObject]@{ ok = $false; error = "source file $SrcPng not found" } | ConvertTo-Json -Compress
            exit 1
        }
        $src = [System.Drawing.Bitmap]::FromFile($SrcPng)
        $x = [Math]::Max(0, [Math]::Min($CropX, $src.Width - 1))
        $y = [Math]::Max(0, [Math]::Min($CropY, $src.Height - 1))
        $w = [Math]::Max(1, [Math]::Min($CropW, $src.Width - $x))
        $h = [Math]::Max(1, [Math]::Min($CropH, $src.Height - $y))
        $rect = New-Object System.Drawing.Rectangle($x, $y, $w, $h)
        $crop = $src.Clone($rect, $src.PixelFormat)
        $src.Dispose()

        $outDir = [System.IO.Path]::GetDirectoryName($CropOut)
        if ($outDir -and -not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
        $crop.Save($CropOut, [System.Drawing.Imaging.ImageFormat]::Png)
        $crop.Dispose()
        [PSCustomObject]@{ ok = $true; path = $CropOut; width = $w; height = $h } | ConvertTo-Json -Compress
    } catch {
        [PSCustomObject]@{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
        exit 1
    }
    exit 0
}

if ($Action -eq "PngToRgba") {
    try {
        Add-Type -AssemblyName System.Drawing
        if (-not (Test-Path $SrcPng)) {
            [PSCustomObject]@{ ok = $false; error = "source file $SrcPng not found" } | ConvertTo-Json -Compress
            exit 1
        }
        $src = [System.Drawing.Bitmap]::FromFile($SrcPng)
        $w = $src.Width
        $h = $src.Height
        $rect = New-Object System.Drawing.Rectangle(0, 0, $w, $h)
        $bmpData = $src.LockBits($rect, [System.Drawing.Imaging.ImageLockMode]::ReadOnly, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $bytes = [Math]::Abs($bmpData.Stride) * $h
        $rgbValues = New-Object byte[] $bytes
        [System.Runtime.InteropServices.Marshal]::Copy($bmpData.Scan0, $rgbValues, 0, $bytes)
        $src.UnlockBits($bmpData)
        $src.Dispose()

        $outDir = [System.IO.Path]::GetDirectoryName($DstRgba)
        if ($outDir -and -not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
        $fs = New-Object System.IO.FileStream($DstRgba, [System.IO.FileMode]::Create)
        $bw = New-Object System.IO.BinaryWriter($fs)
        $bw.Write([int32]$w)
        $bw.Write([int32]$h)
        $bw.Write($rgbValues)
        $bw.Close()
        $fs.Close()
        [PSCustomObject]@{ ok = $true; width = $w; height = $h; path = $DstRgba } | ConvertTo-Json -Compress
    } catch {
        [PSCustomObject]@{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
        exit 1
    }
    exit 0
}

if ($Action -eq "GetCanvasRect") {
    try {
        Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes -ErrorAction SilentlyContinue
        $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $TargetPid)
        $win = [System.Windows.Automation.AutomationElement]::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
        if ($win) {
            $paneCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Pane)
            $panes = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $paneCond)
            $best = $null
            $maxArea = 0
            foreach ($p in $panes) {
                $r = $p.Current.BoundingRectangle
                $area = $r.Width * $r.Height
                if ($area -gt $maxArea) {
                    $maxArea = $area
                    $best = $r
                }
            }
            if ($best) {
                [PSCustomObject]@{ ok = $true; x = $best.X; y = $best.Y; width = $best.Width; height = $best.Height } | ConvertTo-Json -Compress
                exit 0
            }
        }
        [PSCustomObject]@{ ok = $false; error = "canvas not located" } | ConvertTo-Json -Compress
    } catch {
        [PSCustomObject]@{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
        exit 1
    }
    exit 0
}

[PSCustomObject]@{ ok = $false; error = "unknown action $Action" } | ConvertTo-Json -Compress
exit 1
