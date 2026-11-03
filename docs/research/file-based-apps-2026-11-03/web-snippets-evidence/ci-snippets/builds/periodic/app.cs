#!/usr/bin/env -S dotnet --
#:property TargetFramework=net10.0
#:property PublishAot=false
using var timer = new PeriodicTimer(TimeSpan.FromSeconds(1));
using var cancellation = new CancellationTokenSource();
ConsoleCancelEventHandler cancelHandler = (_, eventArgs) =>
{
    eventArgs.Cancel = true;
    cancellation.Cancel();
};
Console.CancelKeyPress += cancelHandler;

try
{
    while (await timer.WaitForNextTickAsync(cancellation.Token))
    {
        Console.WriteLine(DateTimeOffset.Now);
    }
}
catch (OperationCanceledException) when (cancellation.IsCancellationRequested)
{
}
finally
{
    Console.CancelKeyPress -= cancelHandler;
}
